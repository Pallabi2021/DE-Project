# Autonomous DQ & AI Reliability Platform: Observability Report
*Generated: 2026-10-11T11:51:23.569707+00:00*

---

## 1. Executive Summary

This operational report aggregates end-to-end reliability metrics from pipeline execution logs (`metadata/runs.jsonl`), data quality incident tracking (`metadata/incidents.jsonl`), and safety guardrail audit events (`metadata/audit.jsonl`).

| Metric Category | Key Indicator | Current Status |
| :--- | :--- | :--- |
| **Pipeline Availability** | Success Rate | **33.3%** (1/3 runs) |
| **Recovery Efficiency** | Mean Time to Remediation (MTTR) | **1157.59 seconds (19.29 min)** |
| **Data Quality Triage** | Total Incidents Detected | **2** |
| **Security & Safety** | Guardrail Interventions | **20** (3 blocked, 6 flagged) |

---

## 2. Pipeline Health Metrics

- **Total Pipeline Runs Executed:** `3`
- **Successful Runs:** `1`
- **Failed Runs:** `2`
- **Overall Pipeline Success Rate:** `33.33%`
- **Mean Time to Remediation (MTTR):** `1157.59 seconds (19.29 min)` (over 2 resolved incident cycles)

---

## 3. Incident Breakdown by Failure Type

Data quality validations enforce strict multi-layer checks on Bronze and Silver Delta layers. The observed incidents break down as follows:

| Incident Type | Occurrences | Share | Description |
| :--- | :---: | :---: | :--- |
| **Schema Drift** | `2` | 33.3% | Missing required schema columns (e.g. `country`) |
| **Duplicate Primary Keys** | `2` | 33.3% | Duplicate entity IDs violating primary key uniqueness |
| **Null Mandatory Values** | `2` | 33.3% | Missing non-nullable fields (e.g. `email`) |
| **Other / Security** | `0` | 0.0% | Adversarial attempts / unauthorized queries |

### Severity Distribution
- **HIGH Severity:** 2

### Frequently Impacted Fields
- **`country`**: 2 validation failures
- **`customer_id`**: 2 validation failures
- **`email`**: 2 validation failures

---

## 4. Guardrail Intervention & Safety Stats

The autonomous agent's proposed remediations are enforced by strict deterministic guardrails. Higher-risk recovery operations mandate human authorization, and non-allowlisted actions are proactively blocked.

| Guardrail Outcome | Count | Percentage | Operational Policy |
| :--- | :---: | :---: | :--- |
| **Actions Allowed** | `11` | 55.0% | Low-risk, allowlisted autonomous remediations |
| **Human Approval Required** | `6` | 30.0% | High-risk schema evolution or multi-stage changes |
| **Actions Blocked** | `3` | 15.0% | Unsafe SQL, destructive DDL, or non-allowlisted commands |
| **Total Guardrail Events** | `20` | 100.0% | Complete immutable audit trail |

### Action Distribution
- **`reprocess_with_schema_evolution`**: 11 calls
- **`deduplicate_silver`**: 3 calls
- **`quarantine_invalid_records`**: 3 calls
- **`refusal`**: 3 calls

---

## 5. Architectural Recommendations & Best Practices

1. **Auto Loader Schema Evolution:** Automate Bronze schema ingestion with Databricks Auto Loader rescue data column (`_rescued_data`) to prevent raw schema drift drops.
2. **Delta Live Tables Expectations:** Continue gating Gold layer publication behind Delta Lake expectations (`fail_update` on primary key and not-null constraints).
3. **Audited Remediation Workflows:** Maintain human-in-the-loop review for schema evolution and replay actions to uphold high data governance standards.
