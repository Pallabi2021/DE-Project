# Runbook: Pipeline Recovery Procedures

## Overview
General recovery procedures for the data pipeline after incident resolution.

## Replay Mechanisms
- **Full replay**: Re-ingest the original raw file through Bronze -> Silver -> Gold stages after the root cause is fixed.
- **Partial replay**: If only certain rows were affected (e.g., quarantined), re-run Silver validation on the corrected subset and merge into the existing Silver table.
- **Idempotency**: Each run is identified by a unique `run_id`. Replays generate a new `run_id` to avoid overwriting prior audit trails.

## Pre-Recovery Checklist
1. Confirm the root cause has been identified and documented in the incident record.
2. Verify that the remediation action is on the approved allowlist.
3. For MEDIUM or HIGH risk actions, ensure human approval has been granted.
4. Back up current Silver/Gold tables before applying changes.

## Post-Remediation Validation
1. Re-run all DQ checks (schema drift, null values, duplicate records) on the remediated dataset.
2. Compare row counts and key distributions against the last known-good run.
3. Validate that no new incidents are raised by the remediated data.
4. Confirm Gold layer metrics are consistent with expected business rules.

## Escalation Criteria
- If the same incident type recurs more than 3 times in 7 days, escalate to the upstream data provider.
- If remediation alters more than 10% of records, require senior engineer review.
- If Gold-layer metrics deviate more than 5% from baseline after remediation, halt publication and investigate.

## Audit & Logging
- All recovery actions must be logged to `metadata/runs.jsonl` and `metadata/incidents.jsonl`.
- Pipeline logs for recovery runs are stored in `logs/pipeline_RUN-*.log`.
- Incident status must be updated from OPEN to RESOLVED (or ESCALATED) after recovery.
