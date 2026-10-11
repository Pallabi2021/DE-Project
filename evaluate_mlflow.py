#!/usr/bin/env python3
"""
MLflow Agent Evaluation Tracking
Integrates AI Agent golden evaluation with MLflow tracking.
Falls back to a local file-based tracker if MLflow is not installed or unreachable.

Logs:
- Parameters: model_name, prompt_version, agent_version, number_of_test_cases
- Metrics: accuracy, precision, guardrail_pass_rate, avg_latency_ms
- Artifacts: evaluation report, golden test cases, sample predictions
- Default Tracking URI: file:./mlruns
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluate_agent import evaluate_case
from src.agent.guardrails import GuardrailService
from src.agent.investigator import AIInvestigator


class LocalFallbackMLflowTracker:
    """
    Mock/local file tracker providing an identical tracking interface
    when MLflow is not installed or the remote server is unreachable.
    Stores metadata and artifacts under file:./mlruns.
    """
    def __init__(self, tracking_uri: str, experiment_name: str):
        self.tracking_uri = tracking_uri
        self.experiment_name = experiment_name
        self.run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

        # Resolve directory from file: URI
        if tracking_uri.startswith("file:"):
            clean_path = tracking_uri.replace("file:", "").lstrip("/")
            # Handle Windows vs Posix paths
            self.base_dir = PROJECT_ROOT / clean_path
        else:
            self.base_dir = PROJECT_ROOT / "mlruns"

        self.run_dir = self.base_dir / self.experiment_name / self.run_id
        self.artifacts_dir = self.run_dir / "artifacts"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.params: Dict[str, Any] = {}
        self.metrics: Dict[str, Any] = {}

    def log_param(self, key: str, value: Any) -> None:
        self.params[key] = value

    def log_metric(self, key: str, value: float) -> None:
        self.metrics[key] = value

    def log_artifact(self, local_path: str, artifact_path: str = None) -> None:
        src = Path(local_path)
        if not src.is_absolute():
            src = PROJECT_ROOT / src
        if src.exists():
            dest = self.artifacts_dir / (artifact_path or "") / src.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(src.read_bytes())

    def finish(self) -> None:
        # Save run meta
        meta = {
            "run_id": self.run_id,
            "experiment_name": self.experiment_name,
            "tracking_uri": self.tracking_uri,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "params": self.params,
            "metrics": self.metrics,
            "artifacts_dir": str(self.artifacts_dir.relative_to(PROJECT_ROOT)),
        }
        with open(self.run_dir / "run_metadata.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)


def run_evaluation() -> Dict[str, Any]:
    """Executes the evaluation against golden incidents dataset."""
    golden_file = PROJECT_ROOT / "data" / "evaluation" / "golden_incidents.json"
    if not golden_file.exists():
        raise FileNotFoundError(f"Golden dataset not found: {golden_file}")

    with open(golden_file, "r", encoding="utf-8") as f:
        cases = json.load(f)

    investigator = AIInvestigator()
    guardrails = GuardrailService()

    case_results = []
    sample_predictions = []

    for c in cases:
        eval_res = evaluate_case(c, investigator, guardrails, verbose=False)
        case_results.append(eval_res)
        sample_predictions.append({
            "case_id": eval_res["case_id"],
            "name": eval_res["name"],
            "actual_root_cause": eval_res["actual"]["root_cause"],
            "proposed_remediation": eval_res["actual"]["proposed_action"],
            "risk_level": eval_res["actual"]["risk_level"],
            "requires_human_approval": eval_res["actual"]["requires_human_approval"],
            "guardrail_status": eval_res["actual"]["guardrail_status"],
            "passed": eval_res["passed"],
        })

    total = len(case_results)
    passed = sum(1 for r in case_results if r["passed"])
    rc_passed = sum(1 for r in case_results if r["root_cause_matched"])
    rem_passed = sum(1 for r in case_results if r["remediation_aligned"])
    guard_passed = sum(1 for r in case_results if r["guardrail_compliant"])
    avg_latency = round(sum(r["latency_ms"] for r in case_results) / total, 2) if total > 0 else 0.0

    accuracy = round(passed / total, 4) if total > 0 else 0.0
    precision = round(rc_passed / total, 4) if total > 0 else 0.0
    guardrail_pass_rate = round(guard_passed / total, 4) if total > 0 else 0.0

    # Save sample predictions artifact
    metadata_dir = PROJECT_ROOT / "metadata"
    metadata_dir.mkdir(exist_ok=True, parents=True)
    sample_pred_path = metadata_dir / "sample_predictions.json"
    with open(sample_pred_path, "w", encoding="utf-8") as f:
        json.dump(sample_predictions, f, indent=2)

    return {
        "total_cases": total,
        "accuracy": accuracy,
        "precision": precision,
        "guardrail_pass_rate": guardrail_pass_rate,
        "avg_latency_ms": avg_latency,
        "sample_predictions_file": sample_pred_path,
        "golden_file": golden_file,
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate AI Agent and log results to MLflow.")
    parser.add_argument("--tracking-uri", default="file:./mlruns", help="MLflow tracking URI (default: file:./mlruns)")
    parser.add_argument("--experiment-name", default="agent_incident_investigation", help="MLflow experiment name")
    args = parser.parse_args()

    print("================================================================================")
    print("                      MLFLOW AGENT EVALUATION LOGGING                           ")
    print(f" Tracking URI:    {args.tracking_uri}")
    print(f" Experiment Name: {args.experiment_name}")
    print("================================================================================\n")

    # Run evaluation
    eval_metrics = run_evaluation()

    # Model and version parameters
    model_name = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo-1106")
    prompt_version = "v1.2.0"
    agent_version = "1.0.0"
    num_test_cases = eval_metrics["total_cases"]

    metrics = {
        "accuracy": eval_metrics["accuracy"],
        "precision": eval_metrics["precision"],
        "guardrail_pass_rate": eval_metrics["guardrail_pass_rate"],
        "avg_latency_ms": eval_metrics["avg_latency_ms"],
    }

    params = {
        "model_name": model_name,
        "prompt_version": prompt_version,
        "agent_version": agent_version,
        "number_of_test_cases": num_test_cases,
    }

    eval_results_file = PROJECT_ROOT / "metadata" / "eval_results.json"
    golden_file = eval_metrics["golden_file"]
    sample_pred_file = eval_metrics["sample_predictions_file"]

    # Try live MLflow tracking first
    use_mlflow = False
    try:
        import mlflow
        mlflow.set_tracking_uri(args.tracking_uri)
        mlflow.set_experiment(args.experiment_name)
        use_mlflow = True
    except Exception as e:
        print(f"[MLFLOW INFO] MLflow live tracking unavailable ({e}). Using local file tracking fallback.")

    if use_mlflow:
        try:
            with mlflow.start_run(run_name=f"eval_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"):
                # Log parameters
                for k, v in params.items():
                    mlflow.log_param(k, v)

                # Log metrics
                for k, v in metrics.items():
                    mlflow.log_metric(k, v)

                # Log artifacts
                if eval_results_file.exists():
                    mlflow.log_artifact(str(eval_results_file))
                if golden_file.exists():
                    mlflow.log_artifact(str(golden_file))
                if sample_pred_file.exists():
                    mlflow.log_artifact(str(sample_pred_file))

            print("[MLFLOW] Run successfully logged to MLflow.")
        except Exception as e:
            print(f"[MLFLOW WARNING] Failed logging with MLflow client: {e}. Falling back to local tracker.")
            use_mlflow = False

    if not use_mlflow:
        tracker = LocalFallbackMLflowTracker(args.tracking_uri, args.experiment_name)
        for k, v in params.items():
            tracker.log_param(k, v)
        for k, v in metrics.items():
            tracker.log_metric(k, v)
        if eval_results_file.exists():
            tracker.log_artifact(str(eval_results_file))
        if golden_file.exists():
            tracker.log_artifact(str(golden_file))
        if sample_pred_file.exists():
            tracker.log_artifact(str(sample_pred_file))
        tracker.finish()
        print(f"[LOCAL TRACKER] Successfully saved run to: {tracker.run_dir}")

    print("\n------------------------------ LOGGED PARAMETERS ------------------------------")
    for k, v in params.items():
        print(f" {k:<25}: {v}")
    print("------------------------------- LOGGED METRICS --------------------------------")
    for k, v in metrics.items():
        print(f" {k:<25}: {v}")
    print("------------------------------ LOGGED ARTIFACTS -------------------------------")
    print(f" - {eval_results_file.name}")
    print(f" - {golden_file.name}")
    print(f" - {sample_pred_file.name}")
    print("================================================================================\n")


if __name__ == "__main__":
    main()
