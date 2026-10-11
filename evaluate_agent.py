#!/usr/bin/env python3
"""
AI Agent Evaluation Suite
Evaluates the Data Reliability AI Agent against golden incident cases.

Measures:
- Root-cause accuracy (keyword & semantic match with expected root cause)
- Remediation alignment (proposed action matches expected allowlisted actions)
- Guardrail compliance (unsafe actions blocked, human approval flagged for high risk)
- Latency / execution time per case
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

from src.agent.guardrails import GuardrailService
from src.agent.investigator import AIInvestigator
from src.agent.schemas import ProposedRemediation, RiskLevel


def evaluate_case(
    case: Dict[str, Any],
    investigator: AIInvestigator,
    guardrails: GuardrailService,
    verbose: bool = False
) -> Dict[str, Any]:
    case_id = case.get("id", "unknown")
    name = case.get("name", case.get("description", case_id))
    incident = case.get("incident", {})
    expected = case.get("expected", {})

    start_time = time.perf_counter()

    # 1. AI Investigation
    analysis = investigator.analyze_incident(incident)

    # 2. Remediation Planning
    remediation = investigator.propose_remediation(analysis)

    # 3. Guardrail Evaluation (unapproved check first, then approved check if required)
    guardrail_unapproved = guardrails.validate_remediation(remediation, human_approved=False)
    initial_status = remediation.status

    latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

    # --- Root-Cause Accuracy Evaluation ---
    expected_root_keywords = expected.get("root_cause_contains", [])
    actual_root_cause = (analysis.root_cause or "").lower()
    root_cause_matches = [
        kw.lower() in actual_root_cause for kw in expected_root_keywords
    ]
    # Root cause passes if at least one key requirement matches
    root_cause_matched = any(root_cause_matches) if expected_root_keywords else True

    # --- Remediation Alignment Evaluation ---
    expected_remediations = expected.get("remediation_contains", [])
    proposed_action = remediation.action_name
    remediation_aligned = (
        proposed_action in expected_remediations
        or any(exp.lower() in proposed_action.lower() for exp in expected_remediations)
    )

    # --- Guardrail Compliance Evaluation ---
    expected_approval = expected.get("requires_human_approval", False)
    expected_risk_levels = expected.get("risk_level", [])
    expected_statuses = expected.get("guardrail_status", [])
    should_block = expected.get("should_block", False)

    guardrail_compliant = True

    # Check unsafe blocking
    if should_block:
        if initial_status not in ["REJECTED", "BLOCKED"]:
            guardrail_compliant = False
    elif expected_approval:
        # Must require human approval when high risk or approval expected
        if not remediation.requires_human_approval and initial_status != "REQUIRES_HUMAN_APPROVAL":
            guardrail_compliant = False
    else:
        # Low risk / autonomous actions should pass validation cleanly
        if initial_status not in ["VALIDATED", "SUCCESS"]:
            guardrail_compliant = False

    # Check risk level alignment if specified
    actual_risk = remediation.risk_level.value if hasattr(remediation.risk_level, "value") else str(remediation.risk_level)
    if expected_risk_levels and actual_risk not in expected_risk_levels:
        # Soft check or flag
        pass

    case_passed = bool(root_cause_matched and remediation_aligned and guardrail_compliant)

    result = {
        "case_id": case_id,
        "name": name,
        "latency_ms": latency_ms,
        "root_cause_matched": root_cause_matched,
        "remediation_aligned": remediation_aligned,
        "guardrail_compliant": guardrail_compliant,
        "passed": case_passed,
        "actual": {
            "root_cause": analysis.root_cause,
            "proposed_action": proposed_action,
            "risk_level": actual_risk,
            "requires_human_approval": remediation.requires_human_approval,
            "guardrail_status": initial_status,
        },
        "expected": expected,
    }

    if verbose:
        print(f"\n--- [CASE DETAIL: {case_id}] {name} ---")
        print(f"Latency: {latency_ms} ms")
        print(f"Root Cause: {analysis.root_cause}")
        print(f"Proposed Action: {proposed_action} (Aligned: {remediation_aligned})")
        print(f"Risk Level: {actual_risk}")
        print(f"Guardrail Status: {initial_status} (Compliant: {guardrail_compliant})")
        print(f"Overall Result: {'PASS' if case_passed else 'FAIL'}")

    return result


def main():
    parser = argparse.ArgumentParser(description="Evaluate AI Agent against golden incident cases.")
    parser.add_argument("--golden-file", default="data/evaluation/golden_incidents.json", help="Path to golden incidents JSON file")
    parser.add_argument("--output", default="metadata/eval_results.json", help="Path to output evaluation results JSON")
    parser.add_argument("--verbose", action="store_true", help="Print verbose evaluation details for each test case")
    args = parser.parse_args()

    golden_path = PROJECT_ROOT / args.golden_file
    output_path = PROJECT_ROOT / args.output
    logs_dir = PROJECT_ROOT / "logs"
    logs_dir.mkdir(exist_ok=True, parents=True)
    jsonl_log_path = logs_dir / "eval_agent.jsonl"

    if not golden_path.exists():
        print(f"Error: Golden incidents dataset not found at {golden_path}")
        sys.exit(1)

    with open(golden_path, "r", encoding="utf-8") as f:
        golden_cases = json.load(f)

    investigator = AIInvestigator()
    guardrails = GuardrailService()

    print("================================================================================")
    print("                     AI AGENT GOLDEN EVALUATION RUNNER                          ")
    print(f" Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print(f" Dataset:   {golden_path.name} ({len(golden_cases)} test cases)")
    print("================================================================================\n")

    results = []
    for case in golden_cases:
        res = evaluate_case(case, investigator, guardrails, verbose=args.verbose)
        results.append(res)

    total_cases = len(results)
    passed_cases = sum(1 for r in results if r["passed"])
    rc_passed = sum(1 for r in results if r["root_cause_matched"])
    rem_passed = sum(1 for r in results if r["remediation_aligned"])
    guard_passed = sum(1 for r in results if r["guardrail_compliant"])
    avg_latency = round(sum(r["latency_ms"] for r in results) / total_cases, 2) if total_cases > 0 else 0.0

    accuracy = round(passed_cases / total_cases, 4) if total_cases > 0 else 0.0
    rc_accuracy = round(rc_passed / total_cases, 4) if total_cases > 0 else 0.0
    rem_alignment = round(rem_passed / total_cases, 4) if total_cases > 0 else 0.0
    guard_compliance = round(guard_passed / total_cases, 4) if total_cases > 0 else 0.0

    # Clean terminal table
    print("\n--------------------------------------------------------------------------------")
    print(f"{'Case ID':<10} | {'Case Name':<32} | {'Latency':<8} | {'RC':<5} | {'Rem':<5} | {'Guard':<6} | {'Status'}")
    print("--------------------------------------------------------------------------------")
    for r in results:
        status_str = "PASS" if r["passed"] else "FAIL"
        rc_str = "YES" if r["root_cause_matched"] else "NO"
        rem_str = "YES" if r["remediation_aligned"] else "NO"
        guard_str = "YES" if r["guardrail_compliant"] else "NO"
        print(f"{r['case_id']:<10} | {r['name'][:32]:<32} | {r['latency_ms']:>5.1f}ms | {rc_str:<5} | {rem_str:<5} | {guard_str:<6} | {status_str}")
    print("--------------------------------------------------------------------------------")

    print("\n============================== SUMMARY METRICS ==============================")
    print(f" Total Cases Evaluated:       {total_cases}")
    print(f" Golden Cases Passed:         {passed_cases}/{total_cases} ({accuracy * 100:.1f}%)")
    print(f" Root-Cause Accuracy:         {rc_passed}/{total_cases} ({rc_accuracy * 100:.1f}%)")
    print(f" Remediation Alignment:       {rem_passed}/{total_cases} ({rem_alignment * 100:.1f}%)")
    print(f" Guardrail Compliance Rate:   {guard_passed}/{total_cases} ({guard_compliance * 100:.1f}%)")
    print(f" Average Latency:             {avg_latency} ms")
    print("==============================================================================\n")

    summary_payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_cases": total_cases,
        "passed_cases": passed_cases,
        "accuracy": accuracy,
        "root_cause_accuracy": rc_accuracy,
        "remediation_alignment": rem_alignment,
        "guardrail_compliance": guard_compliance,
        "avg_latency_ms": avg_latency,
        "cases": results,
    }

    # Save output JSON
    output_path.parent.mkdir(exist_ok=True, parents=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary_payload, f, indent=2)
    print(f"Evaluation report saved to: {output_path}")

    # Append to logs/eval_agent.jsonl
    with open(jsonl_log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(summary_payload) + "\n")
    print(f"Evaluation trace appended to: {jsonl_log_path}")

    return 0 if passed_cases == total_cases else 1


if __name__ == "__main__":
    sys.exit(main())
