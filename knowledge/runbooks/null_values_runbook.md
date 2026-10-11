# Runbook: Null & Missing Values in Mandatory Fields

## Error patterns
- null or whitespace in non-nullable columns (e.g. `email`, `name`, `customer_id`)

## Severity
MEDIUM to HIGH

## Root causes
- optional form fields added upstream
- client validation bypass
- data truncation

## Diagnostic steps
- calculate null rate
- sample affected rows
- check if nulls correlate with specific source channels

## Recommended remediation actions
- `quarantine_invalid_records`: Filter null rows into quarantine table, allowing valid rows to progress
- `fill_default_values`: Fill synthetic defaults (e.g. 'no-email@example.com') if acceptable by compliance

## Risk level
- Low for quarantining invalid rows
- High for synthetic fill

## Guardrails & Policies
- Synthetic defaults must be flagged and distinguishable from real data
- Compliance team approval required before filling PII fields with synthetic values
