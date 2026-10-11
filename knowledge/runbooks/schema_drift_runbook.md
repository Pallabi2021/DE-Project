# Runbook: Schema Drift & Missing Column Resolution

## Error patterns
- missing columns (e.g. `country`)
- type mismatch
- extra unexpected columns

## Severity
HIGH / CRITICAL

## Root causes
- source system API contract change
- unannounced upstream schema migration
- extraction script bug

## Diagnostic steps
- compare current run columns with previous successful run
- inspect raw payload
- check upstream release notes

## Recommended remediation actions
- `reprocess_with_schema_evolution`: Add missing column with default value (e.g., 'UNKNOWN') and reprocess batch
- `backfill_missing_column`: Look up values from customer reference master table
- `quarantine_invalid_records`: Quarantine affected batch while alerting upstream data provider

## Risk level
- Medium (schema evolution)
- High (manual backfill)

## Guardrails & Policies
- Never drop columns silently
- Require human approval if default values alter business logic
