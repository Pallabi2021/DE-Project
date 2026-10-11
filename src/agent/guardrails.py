from datetime import datetime, timezone
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from src.agent.schemas import ProposedRemediation, RiskLevel

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
METADATA_DIR = PROJECT_ROOT / "metadata"

class GuardrailService:
    def __init__(self):
        self.ALLOWED_REMEDIATIONS = [
            "reprocess_with_schema_evolution",
            "backfill_missing_column",
            "quarantine_invalid_records",
            "deduplicate_silver",
            "fill_default_values",
            "full_replay",
            "partial_replay",
        ]

    def log_audit_event(self, action_name: str, status: str, risk_level: str, details: Dict[str, Any], human_approved: bool = False) -> None:
        """Appends an operational audit record to metadata/audit.jsonl."""
        METADATA_DIR.mkdir(exist_ok=True, parents=True)
        audit_file = METADATA_DIR / "audit.jsonl"
        audit_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action_name": action_name,
            "status": status,
            "risk_level": risk_level,
            "human_approved": human_approved,
            "details": details,
        }
        with open(audit_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(audit_record) + "\n")

    def validate_remediation(self, proposed: ProposedRemediation, human_approved: bool = False) -> bool:
        print(f"\n[GUARDRAIL] Validating proposed remediation: {proposed.action_name}")

        # 1. Check against allowlist
        if proposed.action_name not in self.ALLOWED_REMEDIATIONS:
            print(f"[GUARDRAIL] [REJECTED] Action '{proposed.action_name}' is not in the ALLOWED_REMEDIATIONS allowlist.")
            proposed.status = "REJECTED"
            self.log_audit_event(
                action_name=proposed.action_name,
                status="BLOCKED",
                risk_level=str(proposed.risk_level.value if hasattr(proposed.risk_level, 'value') else proposed.risk_level),
                details={"reason": "Action not in allowlist", "action_name": proposed.action_name},
                human_approved=human_approved
            )
            return False

        # 2. Check justification
        if not proposed.justification or len(proposed.justification.strip()) == 0:
            print("[GUARDRAIL] [REJECTED] No justification provided for remediation action.")
            proposed.status = "REJECTED"
            self.log_audit_event(
                action_name=proposed.action_name,
                status="BLOCKED",
                risk_level=str(proposed.risk_level.value if hasattr(proposed.risk_level, 'value') else proposed.risk_level),
                details={"reason": "Missing justification"},
                human_approved=human_approved
            )
            return False

        # 3. Check risk level and human approval requirement
        is_high_risk = (proposed.risk_level == RiskLevel.HIGH or proposed.riskLevel == RiskLevel.HIGH)
        if is_high_risk or proposed.requires_human_approval:
            proposed.requires_human_approval = True
            if not human_approved:
                print(f"[GUARDRAIL] [FLAGGED] Action '{proposed.action_name}' requires human authorization.")
                proposed.status = "REQUIRES_HUMAN_APPROVAL"
                self.log_audit_event(
                    action_name=proposed.action_name,
                    status="REQUIRES_HUMAN_APPROVAL",
                    risk_level=str(proposed.risk_level.value if hasattr(proposed.risk_level, 'value') else proposed.risk_level),
                    details={"reason": "High risk or explicit human approval flag set"},
                    human_approved=human_approved
                )
                return False
            else:
                print(f"[GUARDRAIL] [OVERRIDE] Action '{proposed.action_name}' has received human authorization.")

        print(f"[GUARDRAIL] [PASSED] Remediation plan '{proposed.action_name}' validated successfully.")
        proposed.status = "VALIDATED"
        self.log_audit_event(
            action_name=proposed.action_name,
            status="ALLOWED",
            risk_level=str(proposed.risk_level.value if hasattr(proposed.risk_level, 'value') else proposed.risk_level),
            details={"arguments": proposed.arguments},
            human_approved=human_approved
        )
        return True

    def execute_remediation(self, proposed: ProposedRemediation, human_approved: bool = False) -> Dict[str, Any]:
        # ONLY executes if validation is passed (or approved)
        if not self.validate_remediation(proposed, human_approved=human_approved):
            print(f"[GUARDRAIL] Execution BLOCKED: Remediation did not pass guardrail validation.")
            return {"status": "BLOCKED", "reason": proposed.status}

        print(f"[EXECUTION] Setting state to REMEDIATING for action '{proposed.action_name}'...")
        proposed.status = "REMEDIATING"

        # Action execution
        try:
            print(f"[EXECUTION] Applying parameters: {proposed.arguments}")
            print(f"[EXECUTION] Simulating action '{proposed.action_name}' execution...")
            proposed.status = "SUCCESS"
            print(f"[EXECUTION] Execution completed: status changed to SUCCESS.")
            return {"status": "SUCCESS", "action": proposed.action_name}
        except Exception as e:
            proposed.status = "FAILED"
            print(f"[EXECUTION] Execution error: status changed to FAILED ({e}).")
            return {"status": "FAILED", "error": str(e)}
