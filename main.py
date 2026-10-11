"""
Local entry point for running the Data Engineering pipeline.
Detects data-quality problems, enforces Bronze/Silver/Gold gating,
and generates structured incident records and audit logs.
"""

import argparse
import sys
from pathlib import Path

# Add src to sys.path so imports work cleanly from project root
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.pipeline.data_pipeline import DataPipeline


def print_banner():
    print("=" * 70)
    print("  AUTONOMOUS DATA QUALITY & INCIDENT RESOLUTION PLATFORM")
    print("  Data Engineering Pipeline Execution")
    print("=" * 70)


def run_pipeline_for_file(pipeline: DataPipeline, file_path: str):
    print(f"\n>>> Running pipeline for: {file_path}")
    print("-" * 70)
    print(f"[BRONZE] Ingesting raw data from {file_path}...")

    try:
        result = pipeline.run(file_path)
    except Exception as e:
        print(f"[ERROR] Pipeline execution crashed: {e}")
        return False

    status = result.get("status")
    run_id = result.get("run_id")

    if status == "SUCCESS":
        print("[SILVER] Running DQ checks (Schema, Nulls, Duplicates)... PASS")
        print("[SILVER] Cleaned records written to data/silver/")
        print("[GOLD] Running metrics aggregation...")
        print(f"[GOLD] Publication SUCCESS -> {result.get('gold_output')}")
        print(f"[STATUS] Run completed successfully (Run ID: {run_id})")
        print(f"         Total records processed: {result.get('total_records')}")
        print(f"         Duration: {result.get('duration_sec'):.3f}s")
        return True
    else:
        print("[SILVER] Running DQ checks (Schema, Nulls, Duplicates)...")
        print("[FAILURE] Data quality checks failed!")
        failures = result.get("failures", [])
        for idx, failure in enumerate(failures, 1):
            check_type = failure.get("check_type")
            col = failure.get("column")
            msg = failure.get("message")
            print(f"  {idx}. [{check_type}] Column '{col}': {msg}")

        incident_id = result.get("incident_id")
        print(f"[INCIDENT CREATED] Incident ID: {incident_id}, Severity: HIGH")
        print(f"                  Status: OPEN | Affected records: {result.get('affected_records_count')}/{result.get('total_records')}")
        print("[GOLD] Publication GATED / BLOCKED.")
        print(f"[STATUS] Run marked FAILED (Run ID: {run_id})")
        print(f"         Incident recorded: metadata/incident_{incident_id}.json")
        print(f"         Appended to metadata/incidents.jsonl and metadata/runs.jsonl")
        print(f"         Pipeline logs saved to logs/pipeline_{run_id}.log")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Run local Bronze/Silver/Gold Data Pipeline with Data Quality Gating."
    )
    parser.add_argument(
        "--file",
        type=str,
        default="data/raw/customers_day2.csv",
        help="Path to CSV input file (default: data/raw/customers_day2.csv)",
    )
    parser.add_argument(
        "--run-all",
        action="store_true",
        help="Run Day 1 (baseline success) followed by Day 2 (intentional DQ failures)",
    )

    args = parser.parse_args()

    print_banner()
    project_root = Path(__file__).resolve().parent
    pipeline = DataPipeline(base_dir=str(project_root))

    if args.run_all:
        print("[MODE] Executing sequential run: Baseline Day 1 -> Incident Day 2")
        day1_file = "data/raw/customers_day1.csv"
        day2_file = "data/raw/customers_day2.csv"

        print("\n=== STEP 1: Running Baseline Batch (Day 1) ===")
        run_pipeline_for_file(pipeline, day1_file)

        print("\n=== STEP 2: Running Problem Batch (Day 2) ===")
        run_pipeline_for_file(pipeline, day2_file)
    else:
        run_pipeline_for_file(pipeline, args.file)

    print("\n" + "=" * 70)
    print("SUMMARY OF GENERATED ARTIFACTS:")
    print("  - Metadata files: metadata/runs.jsonl, metadata/incidents.jsonl")
    print("  - Logs directory: logs/pipeline_RUN-*.log")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
