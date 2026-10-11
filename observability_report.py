#!/usr/bin/env python3
"""
Operational Observability and Audit Summary Report Generator
Analyzes pipeline runs, incident records, and audit events from:
- metadata/runs.jsonl
- metadata/incidents.jsonl
- metadata/audit.jsonl

Outputs:
- Terminal formatted operational health report
- Markdown summary report saved to docs/observability_report.md
"""

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent
METADATA_DIR = PROJECT_ROOT / "metadata"
DOCS_DIR = PROJECT_ROOT / "docs"


def load_jsonl(file_path: Path) -> List[Dict[str, Any]]:
    if not file_path.exists():
        return []
    records = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
    return records


def parse_iso(ts_str: Optional[str]) -> Optional[datetime]:
    if not ts_str:
        return None
    try:
        # Standard ISO format with timezone
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return None


def calculate_mttr(incidents: List[Dict[str, Any]], runs: List[Dict[str, Any]], audit_records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calculates Mean Time to Remediation (MTTR) across incidents.
    Looks for time delta between incident creation and remediation/audit resolution.
    """
    resolution_durations_sec = []

    # Map audit events by timestamp or action
    audit_allowed_ts = [
        parse_iso(a.get("timestamp"))
        for a in audit_records
        if a.get("status") in ["ALLOWED", "SUCCESS"] and parse_iso(a.get("timestamp"))
    ]

    # Map runs by run_id
    success_runs = [r for r in runs if r.get("status") == "SUCCESS"]

    for inc in incidents:
        inc_ts = parse_iso(inc.get("timestamp"))
        if not inc_ts:
            continue

        resolved_ts = None
        # Check if incident is marked REMEDIATED or has remediation timestamp
        if inc.get("status") == "REMEDIATED" and inc.get("remediated_at"):
            resolved_ts = parse_iso(inc.get("remediated_at"))

        # Check subsequent successful run
        if not resolved_ts:
            for s_run in success_runs:
                s_ts = parse_iso(s_run.get("timestamp"))
                if s_ts and s_ts > inc_ts:
                    resolved_ts = s_ts
                    break

        # Check subsequent allowed audit event
        if not resolved_ts:
            for a_ts in audit_allowed_ts:
                if a_ts and a_ts > inc_ts:
                    resolved_ts = a_ts
                    break

        if resolved_ts and resolved_ts >= inc_ts:
            delta = (resolved_ts - inc_ts).total_seconds()
            resolution_durations_sec.append(delta)

    if resolution_durations_sec:
        mean_sec = sum(resolution_durations_sec) / len(resolution_durations_sec)
        return {
            "mttr_seconds": round(mean_sec, 2),
            "mttr_formatted": f"{mean_sec:.2f} seconds ({mean_sec / 60:.2f} min)",
            "resolved_incidents_count": len(resolution_durations_sec),
        }

    return {
        "mttr_seconds": 0.0,
        "mttr_formatted": "N/A (no closed incidents)",
        "resolved_incidents_count": 0,
    }


def analyze_observability() -> Dict[str, Any]:
    runs = load_jsonl(METADATA_DIR / "runs.jsonl")
    incidents = load_jsonl(METADATA_DIR / "incidents.jsonl")
    audit = load_jsonl(METADATA_DIR / "audit.jsonl")

    # 1. Pipeline Health Metrics
    total_runs = len(runs)
    success_runs = sum(1 for r in runs if r.get("status") == "SUCCESS")
    failed_runs = sum(1 for r in runs if r.get("status") == "FAILED")
    success_rate = (success_runs / total_runs * 100) if total_runs > 0 else 0.0
    mttr_data = calculate_mttr(incidents, runs, audit)

    # 2. Incident Breakdown by Type
    incident_types = Counter()
    columns_affected = Counter()
    severity_breakdown = Counter()

    for inc in incidents:
        severity_breakdown[inc.get("severity", "UNKNOWN")] += 1
        failures = inc.get("failures", [])
        for f in failures:
            check_type = f.get("check_type", "UNKNOWN")
            incident_types[check_type] += 1
            col = f.get("column")
            if col:
                columns_affected[col] += 1

    # Standard breakdown categorizations
    schema_drift_count = incident_types.get("SCHEMA_DRIFT", 0)
    duplicates_count = incident_types.get("DUPLICATE_RECORDS", 0)
    nulls_count = incident_types.get("NULL_VALUES", 0)
    other_count = sum(v for k, v in incident_types.items() if k not in ["SCHEMA_DRIFT", "DUPLICATE_RECORDS", "NULL_VALUES"])

    # 3. Guardrail Intervention Stats
    actions_allowed = sum(1 for a in audit if a.get("status") in ["ALLOWED", "SUCCESS"])
    actions_approval_required = sum(1 for a in audit if a.get("status") == "REQUIRES_HUMAN_APPROVAL")
    actions_blocked = sum(1 for a in audit if a.get("status") in ["BLOCKED", "REJECTED"])
    total_guardrail_events = len(audit)

    guardrail_actions_counter = Counter(a.get("action_name", "unknown") for a in audit)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pipeline_health": {
            "total_runs": total_runs,
            "success_runs": success_runs,
            "failed_runs": failed_runs,
            "success_rate_pct": round(success_rate, 2),
            "mttr": mttr_data,
        },
        "incident_metrics": {
            "total_incidents": len(incidents),
            "schema_drift": schema_drift_count,
            "duplicate_records": duplicates_count,
            "null_values": nulls_count,
            "other": other_count,
            "by_type": dict(incident_types),
            "by_severity": dict(severity_breakdown),
            "affected_columns": dict(columns_affected),
        },
        "guardrail_metrics": {
            "total_events": total_guardrail_events,
            "actions_allowed": actions_allowed,
            "actions_requiring_human_approval": actions_approval_required,
            "actions_blocked": actions_blocked,
            "action_distribution": dict(guardrail_actions_counter),
        },
    }


def format_markdown_report(metrics: Dict[str, Any]) -> str:
    ph = metrics["pipeline_health"]
    im = metrics["incident_metrics"]
    gm = metrics["guardrail_metrics"]
    ts = metrics["timestamp"]

    md = f"""# Autonomous DQ & AI Reliability Platform: Observability Report
*Generated: {ts}*

---

## 1. Executive Summary

This operational report aggregates end-to-end reliability metrics from pipeline execution logs (`metadata/runs.jsonl`), data quality incident tracking (`metadata/incidents.jsonl`), and safety guardrail audit events (`metadata/audit.jsonl`).

| Metric Category | Key Indicator | Current Status |
| :--- | :--- | :--- |
| **Pipeline Availability** | Success Rate | **{ph['success_rate_pct']:.1f}%** ({ph['success_runs']}/{ph['total_runs']} runs) |
| **Recovery Efficiency** | Mean Time to Remediation (MTTR) | **{ph['mttr']['mttr_formatted']}** |
| **Data Quality Triage** | Total Incidents Detected | **{im['total_incidents']}** |
| **Security & Safety** | Guardrail Interventions | **{gm['total_events']}** ({gm['actions_blocked']} blocked, {gm['actions_requiring_human_approval']} flagged) |

---

## 2. Pipeline Health Metrics

- **Total Pipeline Runs Executed:** `{ph['total_runs']}`
- **Successful Runs:** `{ph['success_runs']}`
- **Failed Runs:** `{ph['failed_runs']}`
- **Overall Pipeline Success Rate:** `{ph['success_rate_pct']:.2f}%`
- **Mean Time to Remediation (MTTR):** `{ph['mttr']['mttr_formatted']}` (over {ph['mttr']['resolved_incidents_count']} resolved incident cycles)

---

## 3. Incident Breakdown by Failure Type

Data quality validations enforce strict multi-layer checks on Bronze and Silver Delta layers. The observed incidents break down as follows:

| Incident Type | Occurrences | Share | Description |
| :--- | :---: | :---: | :--- |
| **Schema Drift** | `{im['schema_drift']}` | {im['schema_drift'] / (sum(im['by_type'].values()) or 1) * 100:.1f}% | Missing required schema columns (e.g. `country`) |
| **Duplicate Primary Keys** | `{im['duplicate_records']}` | {im['duplicate_records'] / (sum(im['by_type'].values()) or 1) * 100:.1f}% | Duplicate entity IDs violating primary key uniqueness |
| **Null Mandatory Values** | `{im['null_values']}` | {im['null_values'] / (sum(im['by_type'].values()) or 1) * 100:.1f}% | Missing non-nullable fields (e.g. `email`) |
| **Other / Security** | `{im['other']}` | {im['other'] / (sum(im['by_type'].values()) or 1) * 100:.1f}% | Adversarial attempts / unauthorized queries |

### Severity Distribution
"""
    for sev, count in im["by_severity"].items():
        md += f"- **{sev} Severity:** {count}\n"

    md += f"""
### Frequently Impacted Fields
"""
    for col, count in im["affected_columns"].items():
        md += f"- **`{col}`**: {count} validation failures\n"

    md += f"""
---

## 4. Guardrail Intervention & Safety Stats

The autonomous agent's proposed remediations are enforced by strict deterministic guardrails. Higher-risk recovery operations mandate human authorization, and non-allowlisted actions are proactively blocked.

| Guardrail Outcome | Count | Percentage | Operational Policy |
| :--- | :---: | :---: | :--- |
| **Actions Allowed** | `{gm['actions_allowed']}` | {gm['actions_allowed'] / (gm['total_events'] or 1) * 100:.1f}% | Low-risk, allowlisted autonomous remediations |
| **Human Approval Required** | `{gm['actions_requiring_human_approval']}` | {gm['actions_requiring_human_approval'] / (gm['total_events'] or 1) * 100:.1f}% | High-risk schema evolution or multi-stage changes |
| **Actions Blocked** | `{gm['actions_blocked']}` | {gm['actions_blocked'] / (gm['total_events'] or 1) * 100:.1f}% | Unsafe SQL, destructive DDL, or non-allowlisted commands |
| **Total Guardrail Events** | `{gm['total_events']}` | 100.0% | Complete immutable audit trail |

### Action Distribution
"""
    for act, count in gm["action_distribution"].items():
        md += f"- **`{act}`**: {count} calls\n"

    md += """
---

## 5. Architectural Recommendations & Best Practices

1. **Auto Loader Schema Evolution:** Automate Bronze schema ingestion with Databricks Auto Loader rescue data column (`_rescued_data`) to prevent raw schema drift drops.
2. **Delta Live Tables Expectations:** Continue gating Gold layer publication behind Delta Lake expectations (`fail_update` on primary key and not-null constraints).
3. **Audited Remediation Workflows:** Maintain human-in-the-loop review for schema evolution and replay actions to uphold high data governance standards.
"""
    return md


def main():
    print("================================================================================")
    print("                 OPERATIONAL OBSERVABILITY & AUDIT REPORT                       ")
    print(f" Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print("================================================================================\n")

    metrics = analyze_observability()
    ph = metrics["pipeline_health"]
    im = metrics["incident_metrics"]
    gm = metrics["guardrail_metrics"]

    # Terminal report
    print("---------------------------- PIPELINE HEALTH METRICS ---------------------------")
    print(f" Total Pipeline Runs:          {ph['total_runs']}")
    print(f" Successful Runs:              {ph['success_runs']}")
    print(f" Failed Runs:                  {ph['failed_runs']}")
    print(f" Success Rate:                 {ph['success_rate_pct']:.2f}%")
    print(f" Mean Time to Remediation:     {ph['mttr']['mttr_formatted']}")

    print("\n------------------------- INCIDENT BREAKDOWN BY TYPE ---------------------------")
    print(f" Total Incidents:              {im['total_incidents']}")
    print(f" - Schema Drift (missing col): {im['schema_drift']}")
    print(f" - Duplicate Primary Keys:     {im['duplicate_records']}")
    print(f" - Null Values in Mandatory:   {im['null_values']}")
    print(f" - Other / Adversarial:        {im['other']}")

    print("\n------------------------- GUARDRAIL INTERVENTION STATS -------------------------")
    print(f" Total Guardrail Events:       {gm['total_events']}")
    print(f" - Actions Allowed:            {gm['actions_allowed']}")
    print(f" - Human Approval Required:    {gm['actions_requiring_human_approval']}")
    print(f" - Actions Blocked:            {gm['actions_blocked']}")

    # Write Markdown Report to docs/observability_report.md
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    report_file = DOCS_DIR / "observability_report.md"
    markdown_content = format_markdown_report(metrics)
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(markdown_content)

    print(f"\nOperational report successfully written to: {report_file}")
    print("================================================================================\n")


if __name__ == "__main__":
    main()
