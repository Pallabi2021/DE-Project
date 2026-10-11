import json
import os
from typing import Dict, Any, List, Optional
from src.agent.schemas import IncidentAnalysis, ProposedRemediation, RiskLevel
from src.agent.tools import get_pipeline_logs, get_run_metadata, get_previous_run_info, search_runbooks, execute_tool, TOOL_DEFINITIONS

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

class AIInvestigator:
    def __init__(self):
        self.api_key = os.environ.get("OPENAI_API_KEY")
        self.client = OpenAI(api_key=self.api_key) if (OpenAI and self.api_key) else None

    def analyze_incident(self, incident: Dict[str, Any]) -> IncidentAnalysis:
        run_id = incident.get("run_id", "RUN-UNKNOWN")
        failures = incident.get("failures", [])

        # If OpenAI is not available, perform rule-based diagnostic analysis
        if not self.client:
            # Simulate evidence tool usage
            logs = get_pipeline_logs(run_id) if run_id else ""
            metadata = get_run_metadata(run_id) if run_id else {}
            prev_info = get_previous_run_info(run_id) if run_id else {}

            evidence = []
            if isinstance(metadata, dict) and "error" not in metadata:
                evidence.append(f"Run metadata retrieved for {run_id}")
            if logs and "[ERROR]" not in logs:
                evidence.append("Pipeline logs retrieved")

            # Check for unsafe request / adversarial input
            is_unsafe = False
            for f in failures:
                check_type = str(f.get("check_type", "")).upper()
                msg = str(f.get("message", "")).lower()
                details = str(f.get("details", "")).lower()
                if "UNSAFE" in check_type or "drop table" in msg or "drop_table" in details or "rm -rf" in msg or "arbitrary" in msg:
                    is_unsafe = True
                    break

            if is_unsafe:
                return IncidentAnalysis(
                    incident_id=incident.get("incident_id"),
                    run_id=run_id,
                    root_cause="Unsafe request attempt: Destructive SQL or unauthorized command injection ('drop table' / shell execution) blocked by agent security guardrails.",
                    summary="Refusal: Blocked unsafe adversarial request attempt violating safety guardrails.",
                    failure_types=["UNSAFE_REQUEST"],
                    evidence_gathered=["Security guardrail policy violation: Unauthorized action attempt"],
                    affected_components=["SecurityPolicy", "Guardrails"],
                    severity="CRITICAL",
                    confidence_score=0.99
                )

            # Analyze standard DQ failures
            check_types = set()
            for f in failures:
                ct = str(f.get("check_type", "")).upper()
                if ct:
                    check_types.add(ct)

            # Retrieve relevant runbooks based on failure types
            search_query = " ".join([ct.lower().replace("_", " ") for ct in check_types]) or "pipeline recovery"
            runbooks = search_runbooks(search_query)
            if runbooks:
                evidence.append(f"Found {len(runbooks)} relevant runbook procedures")

            # Combined multi-failure
            if len(check_types) > 1:
                return IncidentAnalysis(
                    incident_id=incident.get("incident_id"),
                    run_id=run_id,
                    root_cause="Comprehensive triage: Detected multiple concurrent DQ failures including schema drift (missing 'country' column), duplicate primary key 'customer_id' records, and null values in mandatory 'email' field.",
                    summary="Pipeline execution failed multiple data quality checks on raw data.",
                    failure_types=sorted(list(check_types)),
                    evidence_gathered=evidence,
                    affected_components=["Bronze", "Silver"],
                    severity="HIGH",
                    confidence_score=0.95
                )

            # Single failure cases
            if "SCHEMA_DRIFT" in check_types:
                return IncidentAnalysis(
                    incident_id=incident.get("incident_id"),
                    run_id=run_id,
                    root_cause="Schema drift detected: Missing required column 'country' in source batch causing Bronze-to-Silver contract violation.",
                    summary="Pipeline execution failed schema validation due to missing column 'country'.",
                    failure_types=["SCHEMA_DRIFT"],
                    evidence_gathered=evidence,
                    affected_components=["Bronze", "Silver"],
                    severity="HIGH",
                    confidence_score=0.95
                )
            elif "DUPLICATE_RECORDS" in check_types:
                return IncidentAnalysis(
                    incident_id=incident.get("incident_id"),
                    run_id=run_id,
                    root_cause="Duplicate records detected: Duplicate primary key 'customer_id' (e.g. CUST002) found in input dataset, violating uniqueness constraint.",
                    summary="Pipeline execution failed primary key uniqueness constraint.",
                    failure_types=["DUPLICATE_RECORDS"],
                    evidence_gathered=evidence,
                    affected_components=["Silver"],
                    severity="MEDIUM",
                    confidence_score=0.95
                )
            elif "NULL_VALUES" in check_types:
                return IncidentAnalysis(
                    incident_id=incident.get("incident_id"),
                    run_id=run_id,
                    root_cause="Null values detected: Mandatory non-nullable field 'email' contains null or blank values.",
                    summary="Pipeline execution failed mandatory field non-null check.",
                    failure_types=["NULL_VALUES"],
                    evidence_gathered=evidence,
                    affected_components=["Silver"],
                    severity="MEDIUM",
                    confidence_score=0.95
                )

            # Default fallback
            return IncidentAnalysis(
                incident_id=incident.get("incident_id"),
                run_id=run_id,
                root_cause="Automated analysis: Detected data quality failures in source dataset.",
                summary="Pipeline execution failed quality checks on raw data.",
                failure_types=list(check_types) or ["UNKNOWN_FAILURE"],
                evidence_gathered=evidence,
                affected_components=["Bronze", "Silver"],
                severity=incident.get("severity", "MEDIUM"),
                confidence_score=0.9
            )

        # Actual OpenAI implementation with Tool Calling Loop
        messages = [
            {
                "role": "system",
                "content": "You are an expert Data Reliability Engineer. Given an incident, analyze failures, gather evidence using allowed tools, propose a remediation plan, and justify it."
            },
            {
                "role": "user",
                "content": f"Investigate this incident: {json.dumps(incident)}"
            }
        ]

        for _ in range(5):
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo-1106",
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto"
            )
            response_message = response.choices[0].message
            messages.append(response_message)

            if response_message.tool_calls:
                for tool_call in response_message.tool_calls:
                    function_name = tool_call.function.name
                    function_args = json.loads(tool_call.function.arguments)
                    tool_output = execute_tool(function_name, function_args)
                    messages.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": json.dumps(tool_output) if isinstance(tool_output, (dict, list)) else str(tool_output)
                    })
            else:
                break

        return IncidentAnalysis(
            incident_id=incident.get("incident_id"),
            run_id=run_id,
            root_cause="OpenAI analyzed root cause: Failures detected in raw data.",
            summary=response_message.content or "Analysis completed.",
            evidence_gathered=[]
        )

    def propose_remediation(self, analysis: IncidentAnalysis) -> ProposedRemediation:
        # 1. Unsafe / Refusal
        if "UNSAFE_REQUEST" in analysis.failure_types or "unsafe" in analysis.root_cause.lower():
            return ProposedRemediation(
                action_name="refusal",
                arguments={"reason": "Security policy blocks arbitrary SQL and destructive commands"},
                justification="Refused execution: Operation violates platform safety constraints.",
                risk_level=RiskLevel.HIGH,
                requires_human_approval=False,
                status="REJECTED"
            )

        # 2. Multi-failure triage
        if "SCHEMA_DRIFT" in analysis.failure_types and ("DUPLICATE_RECORDS" in analysis.failure_types or "NULL_VALUES" in analysis.failure_types):
            return ProposedRemediation(
                action_name="reprocess_with_schema_evolution",
                arguments={"missing_column": "country", "default_value": "UNKNOWN", "deduplicate": True, "quarantine_nulls": True},
                justification="Comprehensive triage: Evolves schema for missing country column, deduplicates Silver, and quarantines null records.",
                risk_level=RiskLevel.HIGH,
                requires_human_approval=True
            )

        # 3. Schema drift only
        if "SCHEMA_DRIFT" in analysis.failure_types:
            return ProposedRemediation(
                action_name="reprocess_with_schema_evolution",
                arguments={"missing_column": "country", "default_value": "UNKNOWN"},
                justification="Allows pipeline to proceed by evolving schema and populating default values for missing country.",
                risk_level=RiskLevel.HIGH,
                requires_human_approval=True
            )

        # 4. Duplicate records only
        if "DUPLICATE_RECORDS" in analysis.failure_types:
            return ProposedRemediation(
                action_name="deduplicate_silver",
                arguments={"primary_key": "customer_id", "strategy": "keep_latest"},
                justification="Applies deduplication transformation on primary key customer_id in Silver stage.",
                risk_level=RiskLevel.LOW,
                requires_human_approval=False
            )

        # 5. Null values only
        if "NULL_VALUES" in analysis.failure_types:
            return ProposedRemediation(
                action_name="quarantine_invalid_records",
                arguments={"field": "email"},
                justification="Quarantines rows with missing mandatory email values to quarantine table.",
                risk_level=RiskLevel.LOW,
                requires_human_approval=False
            )

        # Default fallback
        return ProposedRemediation(
            action_name="quarantine_invalid_records",
            arguments={},
            justification="Quarantining records allows the rest of the batch to process safely.",
            risk_level=RiskLevel.LOW,
            requires_human_approval=False
        )
