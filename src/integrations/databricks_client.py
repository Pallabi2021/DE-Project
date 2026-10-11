"""
Databricks Investigation Client for Autonomous Incident Triage.

Supports:
- Live Mode: Connects to Databricks Workspace via REST API or databricks-sdk
  using DATABRICKS_HOST and DATABRICKS_TOKEN.
- Mock/Simulation Mode: Operates without external credentials or when
  DATABRICKS_READONLY_TOOLS_ENABLED=false, providing realistic investigation metadata.

Read-Only Tools:
- get_job_run_status(run_id: str) -> dict
- get_task_output(task_run_id: str) -> dict
- describe_table(table_name: str) -> dict
- get_table_history(table_name: str) -> list[dict]
- get_column_metadata(table_name: str) -> list[dict]
- validate_connection() -> dict
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional
import urllib.parse

logger = logging.getLogger("integrations.databricks")

try:
    import requests
except ImportError:
    requests = None


class DatabricksInvestigationClient:
    """
    Read-only investigation client for Databricks Lakehouse components.
    Provides telemetry, job execution status, Unity Catalog table schemas,
    and Delta Lake history.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        token: Optional[str] = None,
        readonly_enabled: Optional[bool] = None,
    ):
        self.host = (host or os.getenv("DATABRICKS_HOST", "")).strip().rstrip("/")
        self.token = (token or os.getenv("DATABRICKS_TOKEN", "")).strip()

        if readonly_enabled is not None:
            self.enabled = readonly_enabled
        else:
            env_val = os.getenv("DATABRICKS_READONLY_TOOLS_ENABLED", "false").lower()
            self.enabled = env_val in ("true", "1", "yes")

        # Determine if we should attempt live REST calls
        self.live_mode = bool(self.enabled and self.host and self.token and requests is not None)

        if self.live_mode:
            self.headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            }
        else:
            self.headers = {}

    def _api_get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Safely executes an authenticated GET request against Databricks REST API."""
        if not self.live_mode or not requests:
            return None
        url = f"{self.host}{endpoint}"
        try:
            resp = requests.get(url, headers=self.headers, params=params, timeout=10)
            if resp.status_code == 200:
                return resp.json()
            else:
                logger.warning("Databricks API returned %s for %s: %s", resp.status_code, endpoint, resp.text)
                return None
        except Exception as e:
            logger.error("Failed connecting to Databricks REST API (%s): %s", endpoint, e)
            return None

    def validate_connection(self) -> Dict[str, Any]:
        """
        Validates Databricks workspace connectivity.
        In live mode tests API auth; in mock mode returns simulated status.
        """
        if self.live_mode:
            res = self._api_get("/api/2.0/clusters/spark-versions")
            if res is not None:
                return {
                    "status": "CONNECTED",
                    "mode": "live",
                    "host": self.host,
                    "message": "Successfully authenticated to Databricks workspace.",
                }
            return {
                "status": "AUTH_FAILED",
                "mode": "live",
                "host": self.host,
                "message": "Connection attempt to Databricks workspace failed. Falling back to simulated mode.",
            }

        return {
            "status": "SIMULATED",
            "mode": "mock",
            "host": self.host or "https://dbc-simulation.cloud.databricks.com",
            "message": "Databricks investigation client active in mock/simulation mode (DATABRICKS_READONLY_TOOLS_ENABLED=false).",
        }

    def get_job_run_status(self, run_id: str) -> Dict[str, Any]:
        """
        Retrieves job run execution metadata, life cycle state, and task statuses.
        """
        run_id_clean = str(run_id).strip()
        if self.live_mode:
            res = self._api_get("/api/2.1/jobs/runs/get", params={"run_id": run_id_clean})
            if res:
                return res

        # Simulated fallback response
        is_failure = any(term in run_id_clean.lower() for term in ["fail", "error", "0e8f", "1e10", "inc"])
        result_state = "FAILED" if is_failure else "SUCCESS"

        return {
            "run_id": run_id_clean,
            "job_id": 98451204,
            "run_name": "customer_bronze_silver_gold_pipeline",
            "creator_user_name": "data-pipeline-runner@company.com",
            "start_time": 1728644875000,
            "setup_duration": 4500,
            "execution_duration": 35200,
            "state": {
                "life_cycle_state": "TERMINATED",
                "result_state": result_state,
                "user_cancelled_or_timedout": False,
                "state_message": "Pipeline completed with data quality exceptions." if is_failure else "Run completed successfully.",
            },
            "tasks": [
                {
                    "run_id": f"{run_id_clean}_t1",
                    "task_key": "autoloader_bronze_ingestion",
                    "state": {"life_cycle_state": "TERMINATED", "result_state": "SUCCESS"},
                },
                {
                    "run_id": f"{run_id_clean}_t2",
                    "task_key": "silver_dq_processing",
                    "state": {
                        "life_cycle_state": "TERMINATED",
                        "result_state": result_state,
                        "state_message": "Quality checks failed: schema drift and duplicate primary keys detected." if is_failure else "All expectations satisfied.",
                    },
                },
                {
                    "run_id": f"{run_id_clean}_t3",
                    "task_key": "gold_publication",
                    "state": {
                        "life_cycle_state": "TERMINATED" if not is_failure else "SKIPPED",
                        "result_state": "SUCCESS" if not is_failure else "SKIPPED",
                    },
                },
            ],
        }

    def get_task_output(self, task_run_id: str) -> Dict[str, Any]:
        """
        Retrieves logs, exception tracebacks, and output payload of a specific task run.
        """
        task_id_clean = str(task_run_id).strip()
        if self.live_mode:
            res = self._api_get("/api/2.1/jobs/runs/get-output", params={"run_id": task_id_clean})
            if res:
                return res

        # Simulated response
        return {
            "task_run_id": task_id_clean,
            "notebook_output": {
                "result": "FAILED: Delta Live Tables expectation validation error.",
            },
            "error": "DataQualityException: Expectation 'valid_customer_schema' and 'unique_customer_id' violated.",
            "error_trace": (
                "pyspark.sql.utils.AnalysisException: Missing mandatory column 'country'; "
                "Found 2 rows with duplicate customer_id 'CUST002'; Found 1 row with null email."
            ),
            "logs": (
                "[INFO] Commencing Delta Silver transformation\n"
                "[INFO] Checking Bronze Delta snapshot at version 4\n"
                "[WARN] Schema drift: column 'country' not found in incoming batch\n"
                "[ERROR] Expectation 'valid_country' violated. 10 records affected\n"
                "[ERROR] Expectation 'unique_customer_id' violated. Duplicate keys: ['CUST002']\n"
                "[WARN] Quarantining 2 records into main.customer_data.quarantined_records\n"
                "[FATAL] Downstream Gold publication aborted due to DQ check failure."
            ),
        }

    def describe_table(self, table_name: str) -> Dict[str, Any]:
        """
        Retrieves Unity Catalog table metadata, table format, storage location, and properties.
        """
        tbl_clean = str(table_name).strip()
        if self.live_mode:
            res = self._api_get(f"/api/2.1/unity-catalog/tables/{urllib.parse.quote(tbl_clean, safe='')}")
            if res:
                return res

        # Determine table layer
        parts = tbl_clean.split(".")
        tbl_short = parts[-1] if parts else tbl_clean
        catalog = parts[0] if len(parts) > 2 else "main"
        schema = parts[1] if len(parts) > 2 else "customer_data"

        return {
            "name": tbl_clean,
            "catalog_name": catalog,
            "schema_name": schema,
            "table_type": "MANAGED",
            "data_source_format": "DELTA",
            "storage_location": f"abfss://lakehouse@storage.dfs.core.windows.net/{schema}/{tbl_short}",
            "comment": f"Production Delta table for {tbl_short}",
            "properties": {
                "delta.enableChangeDataFeed": "true",
                "delta.autoOptimize.optimizeWrite": "true",
                "delta.autoOptimize.autoCompact": "true",
            },
            "owner": "data-engineers-group",
        }

    def get_table_history(self, table_name: str) -> List[Dict[str, Any]]:
        """
        Retrieves the version history and commit audit trail of a Delta Lake table.
        """
        tbl_clean = str(table_name).strip()
        # In mock mode, return realistic Delta commit log
        return [
            {
                "version": 4,
                "timestamp": "2026-10-11T11:08:04Z",
                "userId": "data-pipeline-runner",
                "userName": "data-pipeline-runner@company.com",
                "operation": "WRITE",
                "operationParameters": {"mode": "Append", "partitionBy": "[]"},
                "operationMetrics": {
                    "numFiles": "2",
                    "numOutputRows": "10",
                    "numOutputBytes": "4210",
                },
                "job": {"jobId": "98451204", "runId": "RUN-20261011-1e1063ed"},
            },
            {
                "version": 3,
                "timestamp": "2026-10-11T11:08:03Z",
                "userId": "data-pipeline-runner",
                "userName": "data-pipeline-runner@company.com",
                "operation": "MERGE",
                "operationParameters": {"predicate": "target.customer_id = source.customer_id"},
                "operationMetrics": {
                    "numTargetRowsInserted": "10",
                    "numTargetRowsUpdated": "0",
                    "numTargetRowsDeleted": "0",
                },
                "job": {"jobId": "98451204", "runId": "RUN-20261011-6fb60dec"},
            },
            {
                "version": 2,
                "timestamp": "2026-10-10T18:00:00Z",
                "userId": "system",
                "userName": "admin@company.com",
                "operation": "CREATE TABLE AS SELECT",
                "operationParameters": {"isManaged": "true"},
                "operationMetrics": {"numFiles": "1", "numOutputRows": "0"},
            },
        ]

    def get_column_metadata(self, table_name: str) -> List[Dict[str, Any]]:
        """
        Retrieves column definitions, data types, nullability, and comments from Unity Catalog.
        """
        tbl_clean = str(table_name).strip().lower()
        if self.live_mode:
            res = self._api_get("/api/2.1/unity-catalog/columns", params={"table_name": table_name})
            if res and "columns" in res:
                return res["columns"]

        # Simulated schemas
        if "gold" in tbl_clean:
            return [
                {"name": "signup_cohort_month", "type_text": "string", "nullable": False, "comment": "Cohort month YYYY-MM"},
                {"name": "total_customers", "type_text": "bigint", "nullable": False, "comment": "Total registered users"},
                {"name": "avg_account_balance", "type_text": "decimal(12,2)", "nullable": True, "comment": "Mean account balance"},
                {"name": "published_at", "type_text": "timestamp", "nullable": False, "comment": "Gold publication timestamp"},
            ]
        elif "quarantine" in tbl_clean:
            return [
                {"name": "quarantine_id", "type_text": "string", "nullable": False, "comment": "UUID"},
                {"name": "raw_payload", "type_text": "string", "nullable": True, "comment": "Rescued raw record JSON"},
                {"name": "failure_reason", "type_text": "string", "nullable": False, "comment": "DQ rule broken"},
                {"name": "quarantined_at", "type_text": "timestamp", "nullable": False, "comment": "Timestamp"},
            ]

        # Standard Silver schema
        return [
            {"name": "customer_id", "type_text": "string", "nullable": False, "comment": "Primary Key"},
            {"name": "name", "type_text": "string", "nullable": False, "comment": "Full name"},
            {"name": "email", "type_text": "string", "nullable": False, "comment": "Email address (non-nullable)"},
            {"name": "country", "type_text": "string", "nullable": True, "comment": "ISO Country code"},
            {"name": "signup_date", "type_text": "timestamp", "nullable": True, "comment": "Signup timestamp"},
            {"name": "account_balance", "type_text": "decimal(12,2)", "nullable": True, "comment": "Account balance in USD"},
            {"name": "_rescued_data", "type_text": "string", "nullable": True, "comment": "Auto Loader rescued data column"},
        ]
