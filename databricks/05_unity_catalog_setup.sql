-- Databricks SQL Setup Script
-- ==============================================================================
-- 05: Unity Catalog Setup, Volume Definitions, Schema Constraints & RBAC
-- ==============================================================================

-- 1. Catalog and Schema Definition
CREATE CATALOG IF NOT EXISTS main
COMMENT 'Production Enterprise Data Lakehouse Catalog';

USE CATALOG main;

CREATE SCHEMA IF NOT EXISTS customer_data
COMMENT 'Customer Data Domain: Bronze ingestion, Silver clean, and Gold presentation layers';

USE SCHEMA customer_data;

-- ==============================================================================
-- 2. Unity Catalog Managed Volumes for Landing & Checkpoints
-- ==============================================================================
CREATE VOLUME IF NOT EXISTS raw_landing
COMMENT 'Raw file drop landing volume for streaming ingestion via Auto Loader';

CREATE VOLUME IF NOT EXISTS checkpoints
COMMENT 'Streaming query checkpoint directories and schema inference state';

-- ==============================================================================
-- 3. Bronze Table Definition (Raw Ingestion Layer)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS customers_bronze (
    customer_id STRING,
    name STRING,
    email STRING,
    country STRING,
    signup_date STRING,
    account_balance STRING,
    _rescued_data STRING COMMENT 'Rescued malformed or schema-drifted columns captured by Auto Loader',
    _ingest_timestamp TIMESTAMP COMMENT 'Timestamp when record entered the lakehouse',
    _source_file_name STRING COMMENT 'URI of the input file parsed by cloudFiles',
    _ingest_batch_id STRING COMMENT 'Unique microbatch execution identifier'
)
USING DELTA
TBLPROPERTIES (
    'delta.enableChangeDataFeed' = 'true',
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact' = 'true'
)
COMMENT 'Bronze raw customer data ingested via Auto Loader with rescue schema preservation';

-- ==============================================================================
-- 4. Silver Table Definition (Cleansed & Enforced Data Quality Layer)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS customers_silver (
    customer_id STRING NOT NULL COMMENT 'Unique customer identifier primary key',
    name STRING NOT NULL COMMENT 'Full name of customer',
    email STRING NOT NULL COMMENT 'Verified non-nullable email address',
    country STRING COMMENT 'ISO country code',
    signup_date TIMESTAMP COMMENT 'Parsed customer registration timestamp',
    account_balance DECIMAL(12, 2) COMMENT 'Current balance in USD',
    _created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
    _updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT pk_customer_id PRIMARY KEY (customer_id)
)
USING DELTA
TBLPROPERTIES (
    'delta.enableChangeDataFeed' = 'true',
    'delta.feature.allowColumnDefaults' = 'supported'
)
COMMENT 'Silver clean customer dimension table with enforced constraints and deduplication';

-- ==============================================================================
-- 5. Quarantined Records Table
-- ==============================================================================
CREATE TABLE IF NOT EXISTS quarantined_records (
    customer_id STRING,
    name STRING,
    email STRING,
    country STRING,
    signup_date STRING,
    account_balance STRING,
    _quarantine_reason STRING NOT NULL COMMENT 'Categorized reason for failure (e.g. SCHEMA_DRIFT, NULL_EMAIL, DUPLICATE_KEY)',
    _quarantine_timestamp TIMESTAMP NOT NULL COMMENT 'When the record was quarantined',
    _source_file STRING
)
USING DELTA
COMMENT 'Isolated records failing Data Quality gates for offline triage and agent root-cause analysis';

-- ==============================================================================
-- 6. Gold Presentation Metrics Table
-- ==============================================================================
CREATE TABLE IF NOT EXISTS customers_gold_metrics (
    country_code STRING NOT NULL COMMENT 'Aggregated country identifier',
    signup_cohort_month STRING NOT NULL COMMENT 'Customer acquisition cohort month YYYY-MM',
    total_customers BIGINT NOT NULL COMMENT 'Count of verified customers',
    avg_account_balance DECIMAL(12, 2) COMMENT 'Mean customer balance',
    total_portfolio_balance DECIMAL(16, 2) COMMENT 'Total portfolio balance sum',
    min_account_balance DECIMAL(12, 2),
    max_account_balance DECIMAL(12, 2),
    _published_at TIMESTAMP NOT NULL COMMENT 'Publication timestamp',
    CONSTRAINT pk_gold_metrics PRIMARY KEY (country_code, signup_cohort_month)
)
USING DELTA
COMMENT 'Gold aggregated customer metrics gated by automated data quality validation';

-- ==============================================================================
-- 7. Role-Based Access Control (RBAC) Grants
-- ==============================================================================

-- Data Engineering Service Principal (Full Pipeline Automation)
GRANT USAGE ON CATALOG main TO `data_engineers`;
GRANT USAGE, CREATE ON SCHEMA customer_data TO `data_engineers`;
GRANT SELECT, MODIFY ON ALL TABLES IN SCHEMA customer_data TO `data_engineers`;
GRANT READ VOLUME, WRITE VOLUME ON VOLUME raw_landing TO `data_engineers`;
GRANT READ VOLUME, WRITE VOLUME ON VOLUME checkpoints TO `data_engineers`;

-- AI Incident Resolution Agent (Strict Least-Privilege Read-Only Triage)
GRANT USAGE ON CATALOG main TO `ai_agent_service_principal`;
GRANT USAGE ON SCHEMA customer_data TO `ai_agent_service_principal`;
GRANT SELECT ON TABLE customers_bronze TO `ai_agent_service_principal`;
GRANT SELECT ON TABLE customers_silver TO `ai_agent_service_principal`;
GRANT SELECT ON TABLE quarantined_records TO `ai_agent_service_principal`;
-- Deny direct DDL, DROP, or write operations to the AI Agent service principal
REVOKE MODIFY ON ALL TABLES IN SCHEMA customer_data FROM `ai_agent_service_principal`;

-- Analytics & BI Consumers (Gold Access Only)
GRANT USAGE ON CATALOG main TO `data_analysts`;
GRANT USAGE ON SCHEMA customer_data TO `data_analysts`;
GRANT SELECT ON TABLE customers_gold_metrics TO `data_analysts`;
