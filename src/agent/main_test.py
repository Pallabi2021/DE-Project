"""
Test runner for AI Investigator, Guardrails, and Remediation Framework.
Loads an existing incident JSON from metadata/, runs the investigation loop,
retrieves evidence, and exercises guardrail validation and remediation execution.
"""

import json
import logging
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.guardrails import GuardrailService
from src.agent.investigator import AIInvestigator
from src.agent.schemas import ProposedRemediation, RiskLevel
from src.agent.tools import (
    get_pipeline_logs,
    get_previous_run_info,
    get_run_metadata,
    search_runbooks,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger("agent.test")


def main():
    print("=" * 80)
    print("  AI AGENT INVESTIGATION & REMEDIATION TEST SUITE")
    print("=" * 80)

    # 1. Load an existing incident JSON from metadata/
    metadata_dir = PROJECT_ROOT / "metadata"
    incident_files = list(metadata_dir.glob("incident_*.json"))
    if not incident_files:
        print("[ERROR] No incident files found in metadata/ directory.")
        return

    target_incident_file = incident_files[0]
    print(f"\n[1] Loading incident file: {target_incident_file.name}")
    incident_data = json.loads(target_incident_file.read_text(encoding="utf-8"))
    
    incident_id = incident_data.get("incident_id")
    run_id = incident_data.get("run_id")
    print(f"    - Incident ID: {incident_id}")
    print(f"    - Associated Run ID: {run_id}")
    print(f"    - Total Failures: {len(incident_data.get('failures', []))}")
    for idx, f in enumerate(incident_data.get("failures", []), 1):
        print(f"      {idx}. [{f.get('check_type')}] {f.get('message')}")

    # 2. Directly verify evidence retrieval tools
    print("\n" + "-" * 80)
    print("[2] Demonstrating Evidence Retrieval Tools:")
    print("-" * 80)
    
    print("\n---> A. get_run_metadata(run_id)")
    run_meta = get_run_metadata(run_id)
    print(f"     Status: {run_meta.get('status')}")
    print(f"     Input File: {run_meta.get('input_file')}")
    print(f"     Failures Count: {run_meta.get('dq_failures_count')}")

    print("\n---> B. get_previous_run_info(run_id)")
    prev_run = get_previous_run_info(run_id)
    if "previous_run" in prev_run:
        p = prev_run["previous_run"]
        print(f"     Predecessor Run ID: {p.get('run_id')}")
        print(f"     Predecessor Status: {p.get('status')}")
        print(f"     Predecessor Columns: {p.get('bronze_columns')}")
    else:
        print(f"     Message: {prev_run.get('message')}")

    print("\n---> C. get_pipeline_logs(run_id) (first 3 lines)")
    logs = get_pipeline_logs(run_id)
    log_lines = logs.strip().splitlines()[:3]
    for line in log_lines:
        print(f"     {line}")

    print("\n---> D. search_runbooks('schema drift missing column')")
    runbook_results = search_runbooks("schema drift missing column", top_k=2)
    for res in runbook_results:
        print(f"     Match: [{res.get('title')} - {res.get('section')}] (Score: {res.get('relevance_score')})")
        print(f"     Remediations: {res.get('recommended_remediations')}")

    # 3. Run AI Investigator Loop
    print("\n" + "-" * 80)
    print("[3] Running AI Investigator Loop:")
    print("-" * 80)
    investigator = AIInvestigator()
    analysis = investigator.analyze_incident(incident_data)
    
    print("\n[ANALYSIS RESULT]")
    print(f"  Incident ID:       {analysis.incident_id}")
    print(f"  Root Cause:        {analysis.root_cause}")
    print(f"  Summary:           {analysis.summary}")
    print(f"  Failure Types:     {analysis.failure_types}")
    print(f"  Evidence Gathered: {analysis.evidence_gathered}")

    # 4. Propose Remediation Plan
    print("\n[PROPOSED REMEDIATION]")
    proposal = investigator.propose_remediation(analysis)
    print(f"  Action Name:       {proposal.action_name}")
    print(f"  Arguments:         {proposal.arguments}")
    print(f"  Justification:     {proposal.justification}")
    print(f"  Risk Level:        {proposal.risk_level.value}")

    # 5. Guardrail Service Validation & Execution
    print("\n" + "-" * 80)
    print("[4] Guardrail Service Validation & Remediation Execution:")
    print("-" * 80)
    guardrail = GuardrailService()

    # Scenario A: Standard Proposal
    print("\n--- Scenario A: Validating and Executing Standard Proposed Plan ---")
    exec_res = guardrail.execute_remediation(proposal)
    print(f"Outcome: {exec_res}")

    # Scenario B: High Risk Remediation (Requires Human Approval)
    print("\n--- Scenario B: High Risk Action without Human Approval ---")
    high_risk_plan = ProposedRemediation(
        action_name="backfill_missing_column",
        arguments={"column": "country", "source": "customer_master_db"},
        justification="Manual database backfill requires operational verification.",
        risk_level=RiskLevel.HIGH
    )
    res_b = guardrail.execute_remediation(high_risk_plan, human_approved=False)
    print(f"Outcome without approval: {res_b}")

    print("\n--- Scenario C: High Risk Action WITH Human Approval ---")
    res_c = guardrail.execute_remediation(high_risk_plan, human_approved=True)
    print(f"Outcome with human approval: {res_c}")

    # Scenario D: Action not in Allowlist (Disallowed)
    print("\n--- Scenario D: Disallowed Action (Not in Allowlist) ---")
    unauthorized_plan = ProposedRemediation(
        action_name="drop_table_and_recreate",
        arguments={},
        justification="Quick fix to clear corrupt state.",
        risk_level=RiskLevel.LOW
    )
    res_d = guardrail.execute_remediation(unauthorized_plan)
    print(f"Outcome of disallowed action: {res_d}")

    # Scenario E: Missing Justification
    print("\n--- Scenario E: Missing Justification ---")
    no_justification_plan = ProposedRemediation(
        action_name="quarantine_invalid_records",
        arguments={},
        justification="",
        risk_level=RiskLevel.LOW
    )
    res_e = guardrail.execute_remediation(no_justification_plan)
    print(f"Outcome of unmotivated action: {res_e}")

    print("\n" + "=" * 80)
    print("  ALL INVESTIGATOR, GUARDRAIL, AND REMEDIATION TESTS COMPLETED")
    print("=" * 80)


if __name__ == "__main__":
    main()
