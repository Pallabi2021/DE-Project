# Databricks notebook source
# COMMAND ----------
# MAGIC %md
# MAGIC # 01: Bronze Layer Ingestion with Databricks Auto Loader
# MAGIC
# MAGIC **Purpose:**
# MAGIC Streams raw customer CSV files into a Bronze Delta table with:
# MAGIC - CloudFiles (Auto Loader) schema inference and evolution
# MAGIC - Rescued data column (`_rescued_data`) to prevent data loss on schema drift
# MAGIC - Ingestion metadata columns (`_ingest_timestamp`, `_source_file_name`)
# MAGIC - Managed checkpointing and schema directory

# COMMAND ----------
import os
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType, DoubleType, TimestampType
)

# COMMAND ----------
# Environment and Storage Configuration
CATALOG_NAME = os.getenv("DATABRICKS_CATALOG", "main")
SCHEMA_NAME = os.getenv("DATABRICKS_SCHEMA", "customer_data")
RAW_SOURCE_PATH = os.getenv("RAW_SOURCE_PATH", "/Volumes/main/customer_data/raw_landing/customers")
CHECKPOINT_PATH = f"/Volumes/{CATALOG_NAME}/{SCHEMA_NAME}/checkpoints/bronze_customers"
SCHEMA_LOCATION = f"/Volumes/{CATALOG_NAME}/{SCHEMA_NAME}/checkpoints/bronze_customers_schema"
BRONZE_TABLE_NAME = f"{CATALOG_NAME}.{SCHEMA_NAME}.customers_bronze"

# COMMAND ----------
# Base expected schema for customer ingestion
expected_schema = StructType([
    StructField("customer_id", StringType(), False),
    StructField("name", StringType(), True),
    StructField("email", StringType(), True),
    StructField("country", StringType(), True),
    StructField("signup_date", StringType(), True),
    StructField("account_balance", StringType(), True),
])

# COMMAND ----------
# Auto Loader Streaming Ingestion Pipeline
# Configured with cloudFiles.rescuedDataColumn to capture undeclared or mismatched fields
df_raw_stream = (
    spark.readStream
    .format("cloudFiles")
    .option("cloudFiles.format", "csv")
    .option("header", "true")
    .option("cloudFiles.inferColumnTypes", "true")
    .option("cloudFiles.schemaLocation", SCHEMA_LOCATION)
    .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
    .option("cloudFiles.rescuedDataColumn", "_rescued_data")
    .schema(expected_schema)
    .load(RAW_SOURCE_PATH)
)

# COMMAND ----------
# Enrich with Ingestion Telemetry
df_bronze_enriched = (
    df_raw_stream
    .withColumn("_ingest_timestamp", F.current_timestamp())
    .withColumn("_source_file_name", F.input_file_name())
    .withColumn("_ingest_batch_id", F.expr("uuid()"))
)

# COMMAND ----------
# Write Stream into Delta Bronze Table
query = (
    df_bronze_enriched.writeStream
    .format("delta")
    .outputMode("append")
    .option("checkpointLocation", CHECKPOINT_PATH)
    .option("mergeSchema", "true")
    .trigger(availableNow=True)  # Micro-batch trigger for cost efficiency
    .toTable(BRONZE_TABLE_NAME)
)

query.awaitTermination()

# COMMAND ----------
# Bronze Ingestion Verification
display(spark.table(BRONZE_TABLE_NAME).orderBy(F.col("_ingest_timestamp").desc()).limit(10))
