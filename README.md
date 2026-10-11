# Autonomous Data Quality & AI Incident Resolution Platform on Databricks

An end-to-end portfolio project combining data engineering and
AI-assisted incident investigation. It simulates data-quality failures,
creates incident records, gathers evidence, proposes guarded
resolutions, and supports human approval before controlled remediation.

> **Note:** This is a portfolio/demo implementation. Validate
> configuration, tests, permissions, and security before connecting it
> to production systems.

## Table of Contents

-   [Overview](#overview)
-   [Architecture](#architecture)
-   [Features](#features)
-   [Technology Stack](#technology-stack)
-   [Repository Structure](#repository-structure)
-   [Local Setup](#local-setup)
-   [Run the Pipeline](#run-the-pipeline)
-   [Configure the AI Agent](#configure-the-ai-agent)
-   [Run the API and Dashboard](#run-the-api-and-dashboard)
-   [Databricks Integration](#databricks-integration)
-   [Safety](#safety)
-   [Troubleshooting](#troubleshooting)
-   [Resume Description](#resume-description)

## Overview

Data pipelines can fail because of schema drift, duplicate records, null
values, or unexpected source changes. Engineers then need to inspect
logs, compare previous runs, search runbooks, determine impact, and
decide how to recover.

This project demonstrates a workflow that: 1. Runs a sample
customer-data pipeline. 2. Detects data-quality failures. 3. Creates a
structured incident record. 4. Collects evidence from run metadata,
logs, prior runs, and runbooks. 5. Uses an AI agent to analyze the
incident and suggest a resolution. 6. Applies policy checks and human
approval where required. 7. Executes only explicitly permitted recovery
actions. 8. Validates the result and records an audit trail.

## Architecture

``` text
Sample CSV files
      |
      v
Bronze / ingestion
      |
      v
Silver transformations + DQ checks
      |
      +-----------------------+
      |                       |
    PASS                    FAIL
      |                       |
      v                       v
Gold publication        Incident record
                              |
                              v
                       AI investigator
                        /           \
                       v             v
                  RAG/runbooks   Read-only evidence tools
                        \           /
                         v         v
                        Root-cause analysis
                                |
                                v
                         Resolution planner
                                |
                                v
                         Guardrail checks
                                |
                                v
                       Human approval if needed
                                |
                                v
                      Controlled remediation
                                |
                                v
                      Post-run validation + audit

Application: FastAPI + Streamlit
Observability: traces, evaluation, MLflow
Deployment: Docker / Docker Compose / CI
Databricks: Auto Loader, Delta Lake, Unity Catalog, Jobs API
```

## Features

### Data engineering

-   Sample customer CSV files and reproducible DQ failures.
-   Schema, null, and duplicate checks.
-   Bronze/Silver/Gold pipeline examples.
-   Databricks Auto Loader, Delta Lake, Unity Catalog, and monitoring
    examples.

### AI investigation

-   Structured incident-analysis output.
-   Tool-assisted retrieval of pipeline logs, previous successful runs,
    recent runs, and runbooks.
-   RAG patterns for operational knowledge.
-   Optional read-only Databricks investigation tools for job runs, task
    output, table descriptions, table history, and column metadata.

### Guardrails and remediation

-   Policy checks on proposed actions.
-   Human approval for higher-risk actions.
-   Explicit remediation allowlist.
-   No unrestricted SQL or shell-execution tools exposed to the LLM.
-   Audit records and post-remediation validation.
-   Downstream Gold publication gated by data-quality validation.

### Application and observability

-   FastAPI endpoints for incident workflows.
-   Streamlit incident dashboard.
-   JSONL traces and audit records.
-   Golden evaluation cases and evaluation scripts.
-   MLflow integration.
-   Docker and CI workflow examples.

## Technology Stack

  Area               Technologies
  ------------------ -------------------------------------------
  Language           Python
  Data engineering   PySpark, Delta Lake
  Databricks         Auto Loader, Unity Catalog, Jobs API
  AI                 LLM tool calling, structured outputs, RAG
  API                FastAPI, Uvicorn
  UI                 Streamlit
  Validation         Pydantic, pytest
  Observability      JSONL traces, MLflow
  Deployment         Docker, Docker Compose, GitHub Actions

## Repository Structure

``` text
.
├── .github/                  # CI workflow
├── data/
│   ├── raw/                  # Sample customer CSV files
│   └── evaluation/           # Golden incident cases
├── databricks/               # Databricks notebooks and SQL
├── docs/                     # Architecture/deployment documentation
├── knowledge/                # Runbooks and knowledge base
├── metadata/                 # Run, incident, approval, action records
├── src/
│   ├── agent/                # Agent logic and tools
│   ├── api/                  # FastAPI application
│   ├── integrations/          # Databricks clients
│   └── rag/                  # Retrieval components
├── tests/                    # Automated tests
├── main.py                   # Local demo pipeline entry point
├── dashboard.py              # Streamlit dashboard
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

Folder contents can vary slightly by revision; use the files in your
downloaded ZIP as the source of truth.

## Local Setup

### Prerequisites

-   Python 3.10--3.12 recommended.
-   VS Code or another editor.
-   An OpenAI API key for live AI investigation, if enabled.
-   A Databricks workspace and scoped credentials only for optional
    workspace integration.
-   Docker Desktop only if using Docker.

### 1. Create and activate a virtual environment

**Windows PowerShell:**

``` powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
```

If `py` is unavailable but `python --version` works:

``` powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**macOS/Linux:**

``` bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

``` bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure environment variables

Create `.env` in the project root, using `.env.example` as a template if
present. Example variables:

``` dotenv
OPENAI_API_KEY=
OPENAI_MODEL=
DATABRICKS_READONLY_TOOLS_ENABLED=false
DATABRICKS_HOST=
DATABRICKS_TOKEN=
DATABRICKS_JOB_ID=
DATABRICKS_SQL_WAREHOUSE_ID=
ENABLE_DATABRICKS_EXECUTION=false
```

Use the exact variable names supported by the downloaded code. Never
commit `.env`, API keys, or access tokens. Keep Databricks execution
disabled until you have deliberately configured and tested it.

## Run the Pipeline

From the project root, with `.venv` activated:

``` bash
python main.py
```

The sample pipeline should detect intentional data-quality problems and
create an incident. The supplied day-two customer data is designed to
demonstrate a missing `country` column and a duplicate record. Run IDs
and incident IDs are generated dynamically.

Inspect the terminal output and the `metadata/` and `logs/` directories.

### Run automated tests

``` bash
pytest -q
```

Resolve test failures before proceeding to the API, agent, or
deployment.

## Configure the AI Agent

The local data-quality pipeline and live AI investigation are separate
stages. First verify that `python main.py` creates an incident. Then
configure a valid API key and a model supported by the implementation.

To check whether the `.env` API key is loaded without printing the
secret:

``` powershell
python -c "from dotenv import load_dotenv; import os; load_dotenv(); print('API key loaded:', bool(os.getenv('OPENAI_API_KEY')))"
```

Expected when configured:

``` text
API key loaded: True
```

Use the agent entry point documented in the code or the README included
in your downloaded version. Do not assume a module path without
confirming the corresponding file exists.

## Run the API and Dashboard

Activate `.venv` in each terminal and run services from the project
root.

### FastAPI

``` bash
uvicorn src.api.app:app --reload
```

Open `http://127.0.0.1:8000/docs`.

If the module cannot be imported, confirm that `src/api/app.py` exists
and use the entry point provided by your downloaded version.

### Streamlit

``` bash
streamlit run dashboard.py
```

Open the local URL printed by Streamlit, typically
`http://localhost:8501`. The dashboard is intended for reviewing
incidents, analysis, resolution plans, approvals, execution, and audit
information.

## MLflow and Evaluation

The project includes agent evaluation and MLflow-related scripts. Check
the supplied README, `docs/`, and script options before running them.
Depending on configuration, commands may include:

``` bash
python evaluate_agent.py
python evaluate_mlflow.py
python observability_report.py
```

Use the MLflow startup script supplied for your operating system if one
exists. Check the configured tracking URI instead of assuming a
particular server or database.

## Databricks Integration

The `databricks/` directory contains examples for Auto Loader,
data-quality processing, Gold-layer publication, monitoring queries, and
incident metadata.

To connect a workspace: 1. Configure catalog, schema, storage/volume
paths, and job settings. 2. Use an approved identity with
least-privilege permissions. 3. Configure the Databricks host and token
securely. 4. Set the job and SQL warehouse identifiers where needed. 5.
Validate read-only investigation tools first. 6. Enable execution only
after reviewing approval rules and remediation allowlists.

These notebooks are templates. Adapt paths, permissions, catalog names,
and runtime settings to your workspace.

## Safety

-   Start with read-only investigation.
-   Use least-privilege credentials.
-   Keep Databricks execution disabled until intentionally configured.
-   Require human approval for risky or high-impact actions.
-   Execute only explicitly allowlisted remediation actions.
-   Revalidate data quality after remediation.
-   Block downstream publication when required checks fail.
-   Preserve approval and action audit records.
-   Never place secrets in logs, Git, screenshots, or chat.
-   Do not connect a demo agent to production jobs without security
    review and operational approval.

## Troubleshooting

### `python` is not recognized on Windows

Try `py --version`. If it works, use `py` to create the virtual
environment. Otherwise, repair Python PATH settings and restart VS Code.

### `ModuleNotFoundError`

-   Confirm the terminal is in the project root.
-   Confirm `(.venv)` appears in the prompt.
-   Run `pip install -r requirements.txt`.
-   Verify that the target Python file/module exists before running it.
-   Use the entry point present in your downloaded version; commands may
    differ between revisions.

### API key is not loaded

-   Ensure `.env` is in the project root.
-   Match the environment variable name used by the code.
-   Confirm `python-dotenv` is installed and the app loads the
    environment file.
-   Never print the API key itself.

### No incident appears in the dashboard

Run `python main.py` first and confirm that an incident was created.
Check the metadata path and ensure the API and dashboard use the same
project directory.

### Databricks tools fail

Check the feature flag, host, token, job/warehouse identifiers, and
identity permissions. Test read-only operations before enabling
execution.

## Future Improvements

-   Expand incident types and golden evaluation cases.
-   Measure root-cause accuracy, groundedness, latency, cost, and
    unsafe-action refusal rates.
-   Add role-based access control and a dedicated approval service.
-   Integrate notifications through an approved channel.
-   Add formal data contracts and schema-version management.
-   Add centralized monitoring, secrets management, and
    deployment-specific security.
-   Run load, security, and recovery testing before production use.

## Resume Description

**Autonomous Data Quality & AI Incident Resolution Platform on
Databricks**

Built a portfolio platform combining PySpark-based data-quality
validation, Databricks Auto Loader/Delta Lake examples, RAG-based
incident investigation, LLM tool calling, structured root-cause
analysis, policy guardrails, human-approved remediation, FastAPI,
Streamlit, MLflow evaluation, audit logging, Docker, and CI workflows.

In interviews, clearly distinguish between features tested locally,
features tested against a Databricks workspace, and optional
integrations that are implemented but not yet deployed.
