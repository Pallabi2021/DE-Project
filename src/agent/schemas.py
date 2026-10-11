"""
Pydantic Schemas for AI Investigation, Evidence Gathering, and Remediation.
Defines strict data contracts for agent tool inputs, root-cause analysis, and proposed remediation.
"""

from enum import Enum
import json
from typing import Any, Dict, List, Optional, Union

try:
    from pydantic import BaseModel as _PydanticBaseModel, Field, ConfigDict

    class BaseModel(_PydanticBaseModel):
        """Pydantic BaseModel with compatibility methods for both v1 and v2."""
        model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

        def to_dict(self) -> Dict[str, Any]:
            if hasattr(self, "model_dump"):
                return self.model_dump()
            return self.dict()

        def to_json(self, indent: int = 2) -> str:
            if hasattr(self, "model_dump_json"):
                return self.model_dump_json(indent=indent)
            return self.json(indent=indent)

except ImportError:
    # Lightweight pure-Python fallback for environments where pydantic is not installed
    def Field(default: Any = ..., default_factory: Any = None, description: str = "", alias: str = None, **kwargs):
        return {
            "__field__": True,
            "default": default,
            "default_factory": default_factory,
            "description": description,
            "alias": alias,
        }

    class BaseModel:
        """Pure-Python fallback BaseModel implementing dictionary and JSON serialization."""
        def __init__(self, **kwargs):
            # Resolve annotations and defaults
            cls = self.__class__
            annotations = getattr(cls, "__annotations__", {})

            # Gather class attributes that might be Field objects or default values
            for attr_name in annotations:
                default_val = getattr(cls, attr_name, None)
                if isinstance(default_val, dict) and default_val.get("__field__"):
                    alias = default_val.get("alias")
                    if alias and alias in kwargs:
                        setattr(self, attr_name, kwargs[alias])
                    elif attr_name in kwargs:
                        setattr(self, attr_name, kwargs[attr_name])
                    elif default_val.get("default_factory"):
                        setattr(self, attr_name, default_val["default_factory"]())
                    elif default_val.get("default") is not ...:
                        setattr(self, attr_name, default_val["default"])
                    else:
                        setattr(self, attr_name, None)
                else:
                    if attr_name in kwargs:
                        setattr(self, attr_name, kwargs[attr_name])
                    else:
                        setattr(self, attr_name, default_val)

            # Assign any extra kwargs
            for k, v in kwargs.items():
                if not hasattr(self, k):
                    setattr(self, k, v)

        def model_dump(self) -> Dict[str, Any]:
            res = {}
            for k, v in self.__dict__.items():
                if isinstance(v, BaseModel):
                    res[k] = v.model_dump()
                elif isinstance(v, Enum):
                    res[k] = v.value
                elif isinstance(v, list):
                    res[k] = [item.model_dump() if isinstance(item, BaseModel) else (item.value if isinstance(item, Enum) else item) for item in v]
                elif isinstance(v, dict):
                    res[k] = {dk: (dv.model_dump() if isinstance(dv, BaseModel) else dv) for dk, dv in v.items()}
                else:
                    res[k] = v
            return res

        def dict(self) -> Dict[str, Any]:
            return self.model_dump()

        def to_dict(self) -> Dict[str, Any]:
            return self.model_dump()

        def model_dump_json(self, indent: int = 2) -> str:
            return json.dumps(self.model_dump(), default=str, indent=indent)

        def json(self, indent: int = 2) -> str:
            return self.model_dump_json(indent=indent)

        def to_json(self, indent: int = 2) -> str:
            return self.model_dump_json(indent=indent)

        def __repr__(self) -> str:
            attrs = ", ".join(f"{k}={v!r}" for k, v in self.__dict__.items())
            return f"{self.__class__.__name__}({attrs})"


class RiskLevel(str, Enum):
    """Categorical risk assessment level for proposed remediation actions."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class EvidenceGatheringToolInputs(BaseModel):
    """General inputs schema for agent evidence retrieval tools."""
    run_id: Optional[str] = Field(None, description="The unique identifier for the pipeline execution run (e.g., RUN-20261011-1e1063ed)")
    query: Optional[str] = Field(None, description="Natural language or keyword search query for runbook retrieval")
    tool_name: Optional[str] = Field(None, description="Name of the evidence tool being invoked")


class GetPipelineLogsInput(BaseModel):
    """Input parameters for fetching execution logs of a pipeline run."""
    run_id: str = Field(..., description="Unique pipeline execution run_id whose logs should be retrieved")


class GetRunMetadataInput(BaseModel):
    """Input parameters for retrieving run execution metadata record."""
    run_id: str = Field(..., description="Unique pipeline execution run_id to inspect")


class GetPreviousRunInfoInput(BaseModel):
    """Input parameters for retrieving the preceding run's metadata."""
    run_id: str = Field(..., description="Target run_id whose chronological predecessor should be retrieved")


class SearchRunbooksInput(BaseModel):
    """Input parameters for searching domain runbooks using semantic/keyword retrieval."""
    query: str = Field(..., description="Search query describing the failure or error symptom")
    top_k: int = Field(3, description="Maximum number of relevant runbook sections to return")


class IncidentAnalysis(BaseModel):
    """
    Structured root-cause analysis produced by the AI Investigator.
    Captures failure diagnosis, synthesized evidence, and blast radius.
    """
    incident_id: Optional[str] = Field(None, description="Identifier of the incident investigated")
    run_id: Optional[str] = Field(None, description="Run ID where failure occurred")
    summary: str = Field(..., description="Concise executive summary of the failure event")
    root_cause: str = Field(..., description="In-depth technical root cause diagnosis")
    failure_types: List[str] = Field(default_factory=list, description="Categorized failure types (e.g. SCHEMA_DRIFT, NULL_VALUES, DUPLICATE_RECORDS)")
    evidence_gathered: List[Union[Dict[str, Any], str]] = Field(default_factory=list, description="List of evidence collected during investigation")
    affected_components: List[str] = Field(default_factory=list, description="Affected pipeline stages, datasets, or columns")
    severity: str = Field("HIGH", description="Incident severity level (LOW, MEDIUM, HIGH, CRITICAL)")
    confidence_score: float = Field(0.95, description="Confidence score of the analysis between 0.0 and 1.0")


class ProposedRemediation(BaseModel):
    """
    Actionable remediation plan proposed by the AI Investigator.
    Subject to guardrail validation and optional human-in-the-loop sign-off.
    """
    action_name: str = Field(..., description="Identifier of the remediation action (must match approved catalog)")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Action-specific execution parameters")
    justification: str = Field(..., description="Technical and operational rationale for proposing this remediation")
    riskLevel: RiskLevel = Field(RiskLevel.MEDIUM, description="Assessed risk level: LOW, MEDIUM, or HIGH", alias="risk_level")
    requires_human_approval: bool = Field(False, description="Flag indicating whether human authorization is mandatory")
    status: str = Field("PROPOSED", description="Remediation lifecycle state: PROPOSED, VALIDATED, REQUIRES_HUMAN_APPROVAL, REMEDIATING, SUCCESS, FAILED, REJECTED")

    @property
    def risk_level(self) -> RiskLevel:
        """Convenience property supporting snake_case access."""
        return self.riskLevel

    @risk_level.setter
    def risk_level(self, value: Union[RiskLevel, str]) -> None:
        if isinstance(value, str):
            value = RiskLevel(value)
        self.riskLevel = value


class InvestigationResult(BaseModel):
    """Complete output bundle of the AI Investigator containing analysis and remediation."""
    incident_id: str = Field(..., description="Incident ID investigated")
    run_id: str = Field(..., description="Pipeline run ID")
    analysis: IncidentAnalysis = Field(..., description="Root cause analysis")
    remediation: ProposedRemediation = Field(..., description="Proposed remediation plan")
    iterations_count: int = Field(1, description="Number of agent reasoning/tool loops executed")
