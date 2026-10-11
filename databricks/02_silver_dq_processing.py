# Databricks notebook source
# COMMAND ----------
# MAGIC %md
# MAGIC # 02: Silver Layer Data Quality Validation & Quarantine Routing
# MAGIC
# MAGIC **Purpose:**
# MAGIC Implements multi-dimensional Data Quality (DQ) enforcement for customer data:
# MAGIC - Schema contract validation (no rescued drift data)
# MAGIC - Mandatory field completeness (`email IS NOT NULL`)
# MAGIC - Primary key uniqueness (`customer_id` uniqueness)
# MAGIC - Automated quarantine routing: valid records merge to Silver; violated records route to Quarantine

# COMMAND ----------
import os
from pyspark.sql import functions as F
from pyspark.sql.window import Window
from delta.tables import DeltaTable

# Optional Delta Live Tables import (present when running in DLT context)
try:
    import dlt
    IS_DLT = True
except ImportError:
    IS_DLT = False

# COMMAND ----------
CATALOG_NAME = os.getenv("DATABRICKS_CATALOG", "main")
SCHEMA_NAME = os.getenv("DATABRICKS_SCHEMA", "customer_data")
BRONZE_TABLE = f"{CATALOG_NAME}.{SCHEMA_NAME}.customers_bronze"
SILVER_TABLE = f"{CATALOG_NAME}.{SCHEMA_NAME}.customers_silver"
QUARANTINE_TABLE = f"{CATALOG_NAME}.{SCHEMA_NAME}.quarantined_records"

# COMMAND ----------
# MAGIC %md
# MAGIC ## Data Quality Rules Catalog
# MAGIC - `valid_schema`: `_rescued_data IS NULL` (no malformed/unmapped fields)
# MAGIC - `valid_email`: `email IS NOT NULL AND length(trim(email)) > 0 AND email LIKE '%@%'`
# MAGIC - `valid_country`: `country IS NOT NULL AND length(trim(country)) >= 2`
# MAGIC - `unique_primary_key`: primary key uniqueness on `customer_id`

# COMMAND ----------
if IS_DLT:
    # -------------------------------------------------------------
    # Delta Live Tables Implementation
    # -------------------------------------------------------------

    @dlt.table(
        name="customers_silver_clean",
        comment="Clean, verified customer records adhering to all DQ expectations.",
        table_properties={"quality": "silver"}
    )
    @dlt.expect_or_drop("valid_email", "email IS NOT NULL AND length(trim(email)) > 0")
    @dlt.expect_or_drop("valid_country", "country IS NOT NULL AND length(trim(country)) >= 2")
    @dlt.expect_or_drop("valid_schema", "_rescued_data IS NULL")
    def customers_silver_clean():
        # Window-based deduplication in streaming/microbatch DLT
        window_spec = Window.partitionBy("customer_id").orderBy(F.col("signup_date").desc(), F.col("_ingest_timestamp").desc())
        return (
            dlt.read_stream("customers_bronze")
            .withColumn("_row_num", F.row_number().over(window_spec))
            .filter(F.col("_row_num") == 1)
            .drop("_row_num")
        )

    @dlt.table(
        name="customers_quarantined",
        comment="Failed records quarantined for investigation and root cause analysis."
    )
    def customers_quarantined():
        return (
            dlt.read_stream("customers_bronze")
            .filter("email IS NULL OR length(trim(email)) = 0 OR country IS NULL OR _rescued_data IS NOT NULL")
            .withColumn("_quarantine_reason", F.when(F.col("email").isNull(), "NULL_EMAIL")
                                              .when(F.col("country").isNull(), "MISSING_COUNTRY")
                                              .when(F.col("_rescued_data").isNotNull(), "SCHEMA_DRIFT_RESCUED")
                                              .otherwise("UNKNOWN_DQ_FAILURE"))
            .withColumn("_quarantine_timestamp", F.current_timestamp())
        )

else:
    # -------------------------------------------------------------
    # Standalone PySpark / Databricks Jobs Implementation
    # -------------------------------------------------------------
    print("[INFO] Executing in standalone PySpark Job mode.")

    df_bronze = spark.table(BRONZE_TABLE)

    # 1. Identify schema drift from rescued data
    has_rescued = "_rescued_data" in df_bronze.columns
    schema_condition = F.col("_rescued_data").isNull() if has_rescued else F.lit(True)

    # 2. Duplicate Detection Window
    window_pk = Window.partitionBy("customer_id").orderBy(
        F.col("signup_date").desc_nulls_last(),
        F.col("_ingest_timestamp").desc()
    )
    window_count = Window.partitionBy("customer_id")

    df_flagged = (
        df_bronze
        .withColumn("_pk_count", F.count("*").over(window_count))
        .withColumn("_pk_rank", F.row_number().over(window_pk))
        .withColumn("_is_duplicate", F.col("_pk_count") > 1)
        .withColumn("_is_null_email", F.col("email").isNull() | (F.trim(F.col("email")) == ""))
        .withColumn("_is_missing_country", F.col("country").isNull() | (F.trim(F.col("country")) == ""))
        .withColumn("_is_schema_drift", ~schema_condition)
    )

    # Assign Failure Reason
    df_quarantine = (
        df_flagged
        .filter(
            F.col("_is_duplicate") |
            F.col("_is_null_email") |
            F.col("_is_missing_country") |
            F.col("_is_schema_drift")
        )
        .withColumn("_quarantine_reason", F.concat_ws(", ",
            F.when(F.col("_is_schema_drift"), "SCHEMA_DRIFT").otherwise(None),
            F.when(F.col("_is_duplicate"), "DUPLICATE_KEY").otherwise(None),
            F.when(F.col("_is_null_email"), "NULL_EMAIL").otherwise(None),
            F.when(F.col("_is_missing_country"), "NULL_COUNTRY").otherwise(None)
        ))
        .withColumn("_quarantine_timestamp", F.current_timestamp())
        .select(
            "customer_id", "name", "email", "country", "signup_date", "account_balance",
            "_quarantine_reason", "_quarantine_timestamp"
        )
    )

    # Clean records that satisfy all DQ rules
    df_clean = (
        df_flagged
        .filter(
            (~F.col("_is_null_email")) &
            (~F.col("_is_missing_country")) &
            (~F.col("_is_schema_drift")) &
            (F.col("_pk_rank") == 1)
        )
        .select("customer_id", "name", "email", "country", "signup_date", "account_balance")
    )

    # Write Quarantined Records
    (
        df_quarantine.write
        .format("delta")
        .mode("append")
        .option("mergeSchema", "true")
        .saveAsTable(QUARANTINE_TABLE)
    )

    # Merge Clean Records into Silver Delta Table
    if DeltaTable.isDeltaTable(spark, SILVER_TABLE):
        delta_silver = DeltaTable.forName(spark, SILVER_TABLE)
        (
            delta_silver.alias("target")
            .merge(
                df_clean.alias("source"),
                "target.customer_id = source.customer_id"
            )
            .whenMatchedUpdateAll()
            .whenNotMatchedInsertAll()
            .execute()
        )
    else:
        (
            df_clean.write
            .format("delta")
            .mode("overwrite")
            .saveAsTable(SILVER_TABLE)
        )

    print(f"[SUCCESS] Clean records routed to {SILVER_TABLE}; Quarantined records saved to {QUARANTINE_TABLE}.")
