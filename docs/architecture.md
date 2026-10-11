# Architecture Documentation

## System Overview

The Autonomous Data Quality & AI Incident Resolution Platform follows a layered architecture:

### Data Layer (Bronze → Silver → Gold)
- **Bronze**: Raw ingestion of CSV files with minimal transformation
- **Silver**: Schema validation, null checks, duplicate detection, data type enforcement
- **Gold**: Curated, validated data ready for analytics — only published when all DQ checks pass

### Incident Management Layer
- Structured incident records created on DQ failure
- Each incident captures: failure type, affected columns, row counts, severity, run metadata

### AI Investigation Layer
- Tool-calling LLM agent with read-only evidence-gathering tools
- RAG-based runbook retrieval for operational context
- Structured root-cause analysis output

### Guardrail & Remediation Layer
- Policy checks validate proposed actions against allowlists
- Human approval required for higher-risk remediations
- Only explicitly permitted recovery actions can execute

### Application Layer
- FastAPI serves incident data and workflow endpoints
- Streamlit dashboard for human review and approval
- JSONL traces and audit logging throughout

### Observability Layer
- Run metadata, traces, and evaluation
- MLflow experiment tracking
- Golden evaluation test cases
