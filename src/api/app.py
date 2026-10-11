from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import json
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.agent.investigator import AIInvestigator
from src.agent.guardrails import GuardrailService
from src.pipeline.data_pipeline import DataPipeline

app = FastAPI(title="Autonomous Data Quality & AI Incident Resolution Platform", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Services
investigator = AIInvestigator()
guardrails = GuardrailService()
project_root = Path(__file__).resolve().parent.parent.parent
pipeline = DataPipeline(base_dir=str(project_root))

# Models
class Approver(BaseModel):
    approver: str
    notes: Optional[str] = None

class RemediationPlan(BaseModel):
    # This matches ProposedRemediation schema approximately
    action_name: str
    arguments: Dict[str, Any]
    justification: str

@app.get("/")
async def root():
    return {"message": "Welcome to the Autonomous DQ & AI Incident Resolution Platform"}

@app.get("/health")
async def health():
    return {"status": "ok"}

def load_jsonl(file_path: Path):
    if not file_path.exists():
        return []
    records = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records

@app.get("/incidents")
async def get_incidents():
    return load_jsonl(project_root / "metadata" / "incidents.jsonl")

@app.get("/incidents/{incident_id}")
async def get_incident(incident_id: str):
    incident_file = project_root / "metadata" / f"incident_{incident_id}.json"
    if not incident_file.exists():
        raise HTTPException(status_code=404, detail="Incident not found")

    with open(incident_file, "r", encoding="utf-8") as f:
        return json.load(f)

@app.post("/incidents/{incident_id}/investigate")
async def investigate_incident(incident_id: str):
    incident = await get_incident(incident_id)
    analysis = investigator.analyze_incident(incident)
    # Persist the analysis
    incident["analysis"] = analysis.model_dump()

    # Save the updated incident
    with open(project_root / "metadata" / f"incident_{incident_id}.json", "w", encoding="utf-8") as f:
        json.dump(incident, f, indent=2)

    return analysis.model_dump()

@app.get("/incidents/{incident_id}/analysis")
async def get_analysis(incident_id: str):
    incident = await get_incident(incident_id)
    if "analysis" not in incident:
         raise HTTPException(status_code=404, detail="Analysis not found")
    return incident["analysis"]

@app.post("/incidents/{incident_id}/resolution-plan")
async def get_resolution_plan(incident_id: str):
    incident = await get_incident(incident_id)
    if "analysis" not in incident:
         raise HTTPException(status_code=400, detail="Run investigation first")

    from src.agent.schemas import IncidentAnalysis
    analysis = IncidentAnalysis(**incident["analysis"])
    remediation = investigator.propose_remediation(analysis)

    return remediation.model_dump()

@app.post("/incidents/{incident_id}/approve")
async def approve_incident(incident_id: str, approver: Approver):
    # This should record approval
    incident = await get_incident(incident_id)
    incident["approval"] = approver.model_dump()

    with open(project_root / "metadata" / f"incident_{incident_id}.json", "w", encoding="utf-8") as f:
        json.dump(incident, f, indent=2)

    # Also append to metadata/approvals.jsonl
    with open(project_root / "metadata" / "approvals.jsonl", "a", encoding="utf-8") as f:
        record = approver.model_dump()
        record["incident_id"] = incident_id
        f.write(json.dumps(record) + "\n")

    return {"message": "Approved"}

@app.post("/incidents/{incident_id}/remediate")
async def remediate_incident(incident_id: str):
    incident = await get_incident(incident_id)
    if "analysis" not in incident:
        raise HTTPException(status_code=400, detail="Investigation missing")

    from src.agent.schemas import IncidentAnalysis, ProposedRemediation
    analysis = IncidentAnalysis(**incident["analysis"])
    remediation = investigator.propose_remediation(analysis)

    # Check approval
    human_approved = "approval" in incident

    res = guardrails.execute_remediation(remediation, human_approved=human_approved)

    if res["status"] == "SUCCESS":
        incident["status"] = "REMEDIATED"
        with open(project_root / "metadata" / f"incident_{incident_id}.json", "w", encoding="utf-8") as f:
            json.dump(incident, f, indent=2)

    return res

@app.get("/incidents/{incident_id}/audit")
async def get_incident_audit(incident_id: str):
    audit_file = project_root / "metadata" / "audit.jsonl"
    if not audit_file.exists():
        return []

    records = []
    with open(audit_file, "r", encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            if record.get("incident_id") == incident_id:
                records.append(record)
    return records

@app.get("/runs")
async def get_runs():
    return load_jsonl(project_root / "metadata" / "runs.jsonl")

class PipelineRunRequest(BaseModel):
    file_path: Optional[str] = "data/raw/customers_day2.csv"

@app.post("/runs/trigger")
async def trigger_run(request: PipelineRunRequest):
    result = pipeline.run(request.file_path)
    return result

@app.get("/audit")
async def get_audit():
    return load_jsonl(project_root / "metadata" / "audit.jsonl")

@app.get("/evaluation")
async def get_evaluation():
    # Placeholder
    return {"message": "Evaluation summary"}
