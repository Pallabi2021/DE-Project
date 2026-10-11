# Databricks notebook source
# COMMAND ----------
# MAGIC %md
# MAGIC # 03: Gold Layer Publication Gated by Data Quality Validation
# MAGIC
# MAGIC **Purpose:**
# MAGIC Publishes aggregated analytics into the Gold presentation layer.
# MAGIC Publication is strictly gated:
# MAGIC 1. Reads Silver table data quality metrics.
# MAGIC 2. Verifies integrity constraints (zero duplicates, zero null primary keys, acceptable quarantine ratio).
# MAGIC 3. Aborts publication and triggers an incident alert if gates fail.
# MAGIC 4. Executes atomic Delta merge into Gold table upon gate approval.

# COMMAND ----------
import os
import sys
from pyspark.sql import functions as F
from delta.tables import DeltaTable

# COMMAND ----------
CATALOG_NAME = os.getenv("DATABRICKS_CATALOG", "main")
SCHEMA_NAME = os.getenv("DATABRICKS_SCHEMA", "customer_data")
SILVER_TABLE = f"{CATALOG_NAME}.{SCHEMA_NAME}.customers_silver"
QUARANTINE_TABLE = f"{CATALOG_NAME}.{SCHEMA_NAME}.quarantined_records"
GOLD_TABLE = f"{CATALOG_NAME}.{SCHEMA_NAME}.customers_gold_metrics"

# Quality Gate Thresholds
MAX_PERMISSIBLE_QUARANTINE_RATIO = 0.20  # Max 20% quarantine rate before blocking Gold

# COMMAND ----------
# MAGIC %md
# MAGIC ## Step 1: Pre-Publication Quality Gates Validation

# COMMAND ----------
df_silver = spark.table(SILVER_TABLE)
total_silver_records = df_silver.count()

if total_silver_records == 0:
    raise ValueError(f"[QUALITY GATE FAILED] Silver table '{SILVER_TABLE}' is empty. Aborting Gold publication.")

# Gate A: Primary Key Null Check
null_pks = df_silver.filter(F.col("customer_id").isNull() | (F.trim(F.col("customer_id")) == "")).count()
if null_pks > 0:
    raise ValueError(f"[QUALITY GATE FAILED] Found {null_pks} null or blank primary keys in Silver. Gold publication blocked.")

# Gate B: Primary Key Duplicate Check
duplicate_pks = (
    df_silver.groupBy("customer_id")
    .count()
    .filter(F.col("count") > 1)
    .count()
)
if duplicate_pks > 0:
    raise ValueError(f"[QUALITY GATE FAILED] Found {duplicate_pks} duplicate customer_id keys in Silver. Gold publication blocked.")

# Gate C: Quarantine Failure Ratio Gate
total_quarantined = 0
if spark.catalog.tableExists(QUARANTINE_TABLE):
    total_quarantined = spark.table(QUARANTINE_TABLE).count()

total_processed = total_silver_records + total_quarantined
quarantine_ratio = (total_quarantined / total_processed) if total_processed > 0 else 0.0

print(f"[METRICS] Silver records: {total_silver_records}")
print(f"[METRICS] Quarantined records: {total_quarantined}")
print(f"[METRICS] Quarantine ratio: {quarantine_ratio:.2%}")

if quarantine_ratio > MAX_PERMISSIBLE_QUARANTINE_RATIO:
    raise ValueError(
        f"[QUALITY GATE FAILED] Quarantine ratio {quarantine_ratio:.2%} exceeds maximum permissible threshold "
        f"{MAX_PERMISSIBLE_QUARANTINE_RATIO:.2%}. Gated publication aborted."
    )

print("[QUALITY GATES PASSED] All integrity constraints validated successfully. Proceeding to Gold aggregation.")

# COMMAND ----------
# MAGIC %md
# MAGIC ## Step 2: Gold Aggregations & Business Metrics

# COMMAND ----------
# Clean casting & cohort calculations
df_clean = (
    df_silver
    .withColumn("balance_numeric", F.coalesce(F.col("account_balance").cast("double"), F.lit(0.0)))
    .withColumn("signup_cohort_month", F.coalesce(F.date_format(F.to_timestamp(F.col("signup_date")), "yyyy-MM"), F.lit("UNKNOWN")))
    .withColumn("country_code", F.coalesce(F.upper(F.trim(F.col("country"))), F.lit("UNKNOWN")))
)

df_gold_metrics = (
    df_clean
    .groupBy("country_code", "signup_cohort_month")
    .agg(
        F.count("customer_id").alias("total_customers"),
        F.round(F.avg("balance_numeric"), 2).alias("avg_account_balance"),
        F.round(F.sum("balance_numeric"), 2).alias("total_portfolio_balance"),
        F.round(F.min("balance_numeric"), 2).alias("min_account_balance"),
        F.round(F.max("balance_numeric"), 2).alias("max_account_balance"),
    )
    .withColumn("_published_at", F.current_timestamp())
)

# COMMAND ----------
# MAGIC %md
# MAGIC ## Step 3: Atomic Gold Table Merge

# COMMAND ----------
if DeltaTable.isDeltaTable(spark, GOLD_TABLE):
    delta_gold = DeltaTable.forName(spark, GOLD_TABLE)
    (
        delta_gold.alias("target")
        .merge(
            df_gold_metrics.alias("source"),
            "target.country_code = source.country_code AND target.signup_cohort_month = source.signup_cohort_month"
        )
        .whenMatchedUpdateAll()
        .whenNotMatchedInsertAll()
        .execute()
    )
else:
    (
        df_gold_metrics.write
        .format("delta")
        .mode("overwrite")
        .option("mergeSchema", "true")
        .saveAsTable(GOLD_TABLE)
    )

print(f"[SUCCESS] Gold layer successfully published to {GOLD_TABLE}.")
