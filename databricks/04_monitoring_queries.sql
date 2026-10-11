-- Databricks SQL Notebook / Query Collection
-- ==============================================================================
-- 04: Unity Catalog Monitoring, DQ Failure Tracking & SLA Metrics Queries
-- ==============================================================================

USE CATALOG main;
USE SCHEMA customer_data;

-- ==============================================================================
-- 1. Daily Ingestion Volume & Quality Pass Rates
-- ==============================================================================
SELECT
    DATE(_ingest_timestamp) AS ingest_date,
    COUNT(*) AS total_raw_records,
    COUNT(CASE WHEN _rescued_data IS NOT NULL THEN 1 END) AS schema_drift_count,
    COUNT(CASE WHEN email IS NULL OR TRIM(email) = '' THEN 1 END) AS null_email_count,
    COUNT(CASE WHEN country IS NULL OR TRIM(country) = '' THEN 1 END) AS null_country_count,
    ROUND(
        (1.0 - (COUNT(CASE WHEN _rescued_data IS NOT NULL OR email IS NULL OR country IS NULL THEN 1 END) * 1.0 / COUNT(*))) * 100,
        2
    ) AS daily_quality_pass_percentage
FROM
    customers_bronze
GROUP BY
    DATE(_ingest_timestamp)
ORDER BY
    ingest_date DESC;

-- ==============================================================================
-- 2. Quarantined Records Failure Taxonomy Breakdown
-- ==============================================================================
SELECT
    _quarantine_reason AS failure_category,
    COUNT(*) AS total_quarantined_records,
    MIN(_quarantine_timestamp) AS first_observed_at,
    MAX(_quarantine_timestamp) AS last_observed_at
FROM
    quarantined_records
GROUP BY
    _quarantine_reason
ORDER BY
    total_quarantined_records DESC;

-- ==============================================================================
-- 3. Primary Key Uniqueness & Collision Tracking in Bronze
-- ==============================================================================
SELECT
    customer_id,
    COUNT(*) AS occurrence_count,
    COLLECT_SET(name) AS names_associated,
    MIN(_ingest_timestamp) AS first_seen,
    MAX(_ingest_timestamp) AS latest_seen
FROM
    customers_bronze
GROUP BY
    customer_id
HAVING
    COUNT(*) > 1
ORDER BY
    occurrence_count DESC;

-- ==============================================================================
-- 4. Pipeline SLA Latency Metrics (Landing to Silver/Gold Publishing)
-- ==============================================================================
WITH ingestion_times AS (
    SELECT
        customer_id,
        MIN(_ingest_timestamp) AS landing_time
    FROM
        customers_bronze
    GROUP BY
        customer_id
),
silver_times AS (
    SELECT
        s.customer_id,
        i.landing_time,
        current_timestamp() AS silver_available_time,
        TIMESTAMPDIFF(SECOND, i.landing_time, current_timestamp()) AS latency_seconds
    FROM
        customers_silver s
    JOIN
        ingestion_times i ON s.customer_id = i.customer_id
)
SELECT
    COUNT(*) AS total_records_measured,
    ROUND(AVG(latency_seconds), 2) AS avg_pipeline_latency_sec,
    MAX(latency_seconds) AS max_pipeline_latency_sec,
    PERCENTILE(latency_seconds, 0.95) AS p95_latency_sec,
    COUNT(CASE WHEN latency_seconds <= 300 THEN 1 END) * 100.0 / COUNT(*) AS sla_compliance_pct_under_5min
FROM
    silver_times;

-- ==============================================================================
-- 5. AI Incident Investigation & Guardrail Audit Trail Query
-- ==============================================================================
CREATE TABLE IF NOT EXISTS incident_remediation_audit (
    audit_id STRING,
    incident_id STRING,
    run_id STRING,
    action_name STRING,
    risk_level STRING,
    guardrail_decision STRING, -- 'ALLOWED', 'REQUIRES_HUMAN_APPROVAL', 'BLOCKED'
    human_approved BOOLEAN,
    approver_identity STRING,
    executed_at TIMESTAMP,
    execution_status STRING
) USING DELTA;

SELECT
    DATE(executed_at) AS audit_date,
    guardrail_decision,
    action_name,
    COUNT(*) AS action_count,
    COUNT(CASE WHEN human_approved = TRUE THEN 1 END) AS human_approved_count,
    COUNT(CASE WHEN execution_status = 'SUCCESS' THEN 1 END) AS successful_executions
FROM
    incident_remediation_audit
GROUP BY
    DATE(executed_at),
    guardrail_decision,
    action_name
ORDER BY
    audit_date DESC,
    action_count DESC;
