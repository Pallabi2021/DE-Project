"""
Bronze, Silver, Gold data processing pipeline with data quality checks.
Local execution powered by Pandas, mirroring PySpark concepts and patterns.
"""

import json
import logging
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


class SchemaDriftError(Exception):
    """Raised when incoming dataset schema does not match expected schema."""
    pass


@dataclass
class DQFailure:
    check_type: str  # "SCHEMA_DRIFT" | "DUPLICATE_RECORDS" | "NULL_VALUES"
    column: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DQReport:
    is_valid: bool
    failures: List[DQFailure]
    total_records: int
    affected_records_count: int


class DataPipeline:
    """
    Bronze, Silver, Gold data processing pipeline.

    Expected Schema:
    - customer_id: str, primary key, non-null
    - name: str, non-null
    - email: str, non-null, valid email format
    - country: str, non-null
    - signup_date: str/date, non-null
    - account_balance: float/numeric, non-null
    """

    EXPECTED_COLUMNS = [
        "customer_id",
        "name",
        "email",
        "country",
        "signup_date",
        "account_balance",
    ]

    EMAIL_REGEX = re.compile(r"^[\w\.-]+@[\w\.-]+\.\w+$")

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.metadata_dir = self.base_dir / "metadata"
        self.logs_dir = self.base_dir / "logs"
        self.data_silver_dir = self.base_dir / "data" / "silver"
        self.data_gold_dir = self.base_dir / "data" / "gold"
        self.data_quarantine_dir = self.base_dir / "data" / "quarantine"

        # Ensure directories exist
        for directory in [
            self.metadata_dir,
            self.logs_dir,
            self.data_silver_dir,
            self.data_gold_dir,
            self.data_quarantine_dir,
        ]:
            directory.mkdir(parents=True, exist_ok=True)

    def _setup_logger(self, run_id: str) -> logging.Logger:
        logger = logging.getLogger(f"pipeline_{run_id}")
        logger.setLevel(logging.INFO)
        logger.handlers.clear()

        # File handler
        log_file = self.logs_dir / f"pipeline_{run_id}.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        formatter = logging.Formatter(
            "%(asctime)s - [%(levelname)s] - %(message)s"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        return logger

    def run(self, input_file: str) -> Dict[str, Any]:
        """
        Executes pipeline for given input CSV file.
        Returns execution summary dict with run_id, incident_id (if failed), status, etc.
        """
        start_time = datetime.now(timezone.utc)
        run_date_str = start_time.strftime("%Y%m%d")
        run_uuid = uuid.uuid4().hex[:8]
        run_id = f"RUN-{run_date_str}-{run_uuid}"

        logger = self._setup_logger(run_id)
        logger.info(f"Starting pipeline execution {run_id} for input: {input_file}")

        input_path = Path(input_file)
        if not input_path.is_absolute():
            input_path = self.base_dir / input_path

        if not input_path.exists():
            error_msg = f"Input file not found: {input_path}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)

        # ---------------- BRONZE LAYER: Ingestion ----------------
        logger.info("[BRONZE] Ingesting raw batch...")
        try:
            raw_df = pd.read_csv(input_path, dtype=str)
        except Exception as e:
            logger.error(f"Failed to read CSV: {e}")
            raise

        total_records = len(raw_df)
        logger.info(f"[BRONZE] Ingested {total_records} raw records from {input_path.name}")

        # Save Bronze raw snapshot
        snapshot_file = self.metadata_dir / f"bronze_snapshot_{run_id}.json"
        bronze_snapshot_data = {
            "run_id": run_id,
            "timestamp": start_time.isoformat(),
            "source_file": str(input_path),
            "record_count": total_records,
            "columns": list(raw_df.columns),
            "records": raw_df.to_dict(orient="records"),
        }
        with open(snapshot_file, "w", encoding="utf-8") as f:
            json.dump(bronze_snapshot_data, f, indent=2)
        logger.info(f"[BRONZE] Raw snapshot saved to {snapshot_file.name}")

        # ---------------- SILVER LAYER: Data Quality Checks ----------------
        logger.info("[SILVER] Running DQ checks (Schema, Nulls, Duplicates)...")
        dq_report = self._validate_data_quality(raw_df, logger)

        end_time = datetime.now(timezone.utc)
        duration_sec = (end_time - start_time).total_seconds()

        if not dq_report.is_valid:
            # ---------------- FAILURE WORKFLOW ----------------
            incident_id = f"INC-{run_date_str}-{uuid.uuid4().hex[:8]}"
            logger.warning(
                f"[FAILURE] Data quality checks failed with {len(dq_report.failures)} violations. "
                f"Affected records: {dq_report.affected_records_count}"
            )
            logger.warning(f"[INCIDENT CREATED] Incident ID: {incident_id}, Severity: HIGH")

            # Quarantine bronze batch
            quarantine_file = self.data_quarantine_dir / f"quarantined_{run_id}.csv"
            raw_df.to_csv(quarantine_file, index=False)
            logger.info(f"[SILVER] Quarantined raw batch saved to {quarantine_file.name}")

            # Block publication to silver and gold
            logger.warning("[GOLD] Publication GATED / BLOCKED due to DQ failures.")

            # Construct structured incident record
            incident_record = {
                "incident_id": incident_id,
                "run_id": run_id,
                "timestamp": start_time.isoformat(),
                "status": "OPEN",
                "severity": "HIGH",
                "failures": [asdict(f) for f in dq_report.failures],
                "affected_records_count": dq_report.affected_records_count,
                "total_records": total_records,
                "input_file": str(input_path),
                "bronze_snapshot": str(snapshot_file),
                "quarantine_file": str(quarantine_file),
            }

            # Save metadata/incident_{incident_id}.json
            single_incident_file = self.metadata_dir / f"incident_{incident_id}.json"
            with open(single_incident_file, "w", encoding="utf-8") as f:
                json.dump(incident_record, f, indent=2)

            # Append to metadata/incidents.jsonl
            incidents_jsonl = self.metadata_dir / "incidents.jsonl"
            with open(incidents_jsonl, "a", encoding="utf-8") as f:
                f.write(json.dumps(incident_record) + "\n")

            # Save run record
            failure_reasons = [f.message for f in dq_report.failures]
            run_record = {
                "run_id": run_id,
                "timestamp": start_time.isoformat(),
                "status": "FAILED",
                "input_file": str(input_path),
                "total_records": total_records,
                "duration_sec": round(duration_sec, 3),
                "failure_reasons": failure_reasons,
                "incident_id": incident_id,
                "dq_failures_count": len(dq_report.failures),
                "affected_records": dq_report.affected_records_count,
            }
            runs_jsonl = self.metadata_dir / "runs.jsonl"
            with open(runs_jsonl, "a", encoding="utf-8") as f:
                f.write(json.dumps(run_record) + "\n")

            return {
                "status": "FAILED",
                "run_id": run_id,
                "incident_id": incident_id,
                "failures": [asdict(f) for f in dq_report.failures],
                "affected_records_count": dq_report.affected_records_count,
                "total_records": total_records,
                "duration_sec": duration_sec,
                "snapshot_file": str(snapshot_file),
            }

        # ---------------- SUCCESS WORKFLOW ----------------
        logger.info("[SILVER] DQ checks passed. Processing Silver cleaned dataset...")
        silver_df = raw_df.copy()
        # Cast account_balance to float
        silver_df["account_balance"] = pd.to_numeric(silver_df["account_balance"])
        silver_df["signup_date"] = pd.to_datetime(silver_df["signup_date"])

        silver_file = self.data_silver_dir / f"customers_silver_{run_id}.parquet"
        silver_csv_file = self.data_silver_dir / f"customers_silver_{run_id}.csv"
        silver_df.to_csv(silver_csv_file, index=False)
        try:
            silver_df.to_parquet(silver_file, index=False)
        except Exception:
            pass  # If pyarrow/fastparquet is not present, csv is retained
        logger.info(f"[SILVER] Cleaned data published to {silver_csv_file.name}")

        # ---------------- GOLD LAYER: Aggregation ----------------
        logger.info("[GOLD] Running aggregations...")
        gold_df = (
            silver_df.groupby("country", as_index=False)
            .agg(
                customer_count=("customer_id", "count"),
                total_balance=("account_balance", "sum"),
                avg_balance=("account_balance", "mean"),
            )
            .round({"total_balance": 2, "avg_balance": 2})
        )

        gold_file = self.data_gold_dir / f"customer_metrics_{run_id}.csv"
        gold_df.to_csv(gold_file, index=False)
        logger.info(f"[GOLD] Aggregated metrics published to {gold_file.name}")

        run_record = {
            "run_id": run_id,
            "timestamp": start_time.isoformat(),
            "status": "SUCCESS",
            "input_file": str(input_path),
            "total_records": total_records,
            "duration_sec": round(duration_sec, 3),
            "failure_reasons": [],
            "incident_id": None,
            "silver_output": str(silver_csv_file),
            "gold_output": str(gold_file),
        }
        runs_jsonl = self.metadata_dir / "runs.jsonl"
        with open(runs_jsonl, "a", encoding="utf-8") as f:
            f.write(json.dumps(run_record) + "\n")

        return {
            "status": "SUCCESS",
            "run_id": run_id,
            "incident_id": None,
            "total_records": total_records,
            "duration_sec": duration_sec,
            "silver_output": str(silver_csv_file),
            "gold_output": str(gold_file),
        }

    def _validate_data_quality(self, df: pd.DataFrame, logger: logging.Logger) -> DQReport:
        failures: List[DQFailure] = []
        affected_indices = set()

        # 1. Schema Check
        actual_cols = set(df.columns)
        expected_cols = set(self.EXPECTED_COLUMNS)
        missing_cols = list(expected_cols - actual_cols)

        if missing_cols:
            msg = f"Schema Drift Detected: Missing required columns: {missing_cols}"
            logger.error(f"[DQ-CHECK] {msg}")
            failures.append(
                DQFailure(
                    check_type="SCHEMA_DRIFT",
                    column=",".join(missing_cols),
                    message=msg,
                    details={
                        "missing_columns": missing_cols,
                        "expected_columns": self.EXPECTED_COLUMNS,
                        "actual_columns": list(df.columns),
                    },
                )
            )
            # Schema drift affects all records in batch
            affected_indices.update(range(len(df)))

        # 2. Duplicate Check on Primary Key
        if "customer_id" in df.columns:
            duplicate_mask = df.duplicated(subset=["customer_id"], keep=False)
            dup_records = df[duplicate_mask]
            if not dup_records.empty:
                dup_ids = dup_records["customer_id"].unique().tolist()
                msg = f"Duplicate primary key 'customer_id' detected: {dup_ids} ({len(dup_records)} rows)"
                logger.error(f"[DQ-CHECK] {msg}")
                failures.append(
                    DQFailure(
                        check_type="DUPLICATE_RECORDS",
                        column="customer_id",
                        message=msg,
                        details={
                            "duplicate_customer_ids": dup_ids,
                            "duplicate_row_count": len(dup_records),
                        },
                    )
                )
                affected_indices.update(dup_records.index.tolist())

        # 3. Null / Blank Checks
        columns_to_check = [c for c in self.EXPECTED_COLUMNS if c in df.columns]
        for col in columns_to_check:
            # Check for null, NaN, or whitespace-only
            null_mask = df[col].isna() | (df[col].astype(str).str.strip() == "")
            null_count = null_mask.sum()
            if null_count > 0:
                null_indices = df[null_mask].index.tolist()
                msg = f"Null or blank values found in required column '{col}': {null_count} rows"
                logger.error(f"[DQ-CHECK] {msg}")
                failures.append(
                    DQFailure(
                        check_type="NULL_VALUES",
                        column=col,
                        message=msg,
                        details={
                            "null_count": int(null_count),
                            "affected_row_indices": null_indices,
                        },
                    )
                )
                affected_indices.update(null_indices)

        # 4. Email format check (if email column present)
        if "email" in df.columns:
            non_null_email_mask = ~df["email"].isna() & (df["email"].astype(str).str.strip() != "")
            invalid_email_indices = []
            for idx in df[non_null_email_mask].index:
                email_val = str(df.loc[idx, "email"]).strip()
                if not self.EMAIL_REGEX.match(email_val):
                    invalid_email_indices.append(idx)
            if invalid_email_indices:
                msg = f"Invalid email format in 'email' column: {len(invalid_email_indices)} rows"
                logger.error(f"[DQ-CHECK] {msg}")
                failures.append(
                    DQFailure(
                        check_type="INVALID_FORMAT",
                        column="email",
                        message=msg,
                        details={
                            "invalid_count": len(invalid_email_indices),
                            "affected_row_indices": invalid_email_indices,
                        },
                    )
                )
                affected_indices.update(invalid_email_indices)

        is_valid = len(failures) == 0
        return DQReport(
            is_valid=is_valid,
            failures=failures,
            total_records=len(df),
            affected_records_count=len(affected_indices),
        )
