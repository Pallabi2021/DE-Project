# Runbook: Duplicate Primary Key Records

## Error patterns
- duplicate `customer_id` rows within same batch
- duplicate `customer_id` rows across batches

## Severity
HIGH

## Root causes
- upstream retry without deduplication
- at-least-once message delivery
- race conditions in ingestion

## Diagnostic steps
- identify duplicate keys
- check timestamp/hash of records
- examine if duplicates are exact copies or conflicting mutations

## Recommended remediation actions
- `deduplicate_silver`: Keep latest record based on `signup_date` or latest ingestion timestamp
- `quarantine_invalid_records`: Isolate duplicates to quarantine table for manual reconciliation

## Risk level
- Low for exact duplicates
- Medium for conflicting records

## Guardrails & Policies
- Ensure deterministic deduplication tie-breakers (e.g., timestamp desc, customer_id asc)
