"""
Evidence Gathering Tools for Autonomous Incident Investigation.

Read-only tools exposed to the AI Investigator:
1. get_pipeline_logs(run_id): Fetches log file for a specific pipeline execution.
2. get_run_metadata(run_id): Fetches run execution record and snapshot details.
3. get_previous_run_info(run_id): Fetches predecessor run to determine baseline state.
4. search_runbooks(query): Searches domain runbooks using hybrid BM25 / RAG retriever.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from src.rag.runbook_retriever import RunbookRetriever

logger = logging.getLogger("agent.tools")

# Determine project base directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
METADATA_DIR = PROJECT_ROOT / "metadata"
RUNBOOKS_DIR = PROJECT_ROOT / "knowledge" / "runbooks"

# Singleton retriever instance
_runbook_retriever: Optional[RunbookRetriever] = None


def _get_retriever() -> RunbookRetriever:
    """Lazily initializes and caches RunbookRetriever instance."""
    global _runbook_retriever
    if _runbook_retriever is None:
        _runbook_retriever = RunbookRetriever(runbooks_dir=str(RUNBOOKS_DIR))
    return _runbook_retriever


def get_pipeline_logs(run_id: str) -> str:
    """
    Fetches the log file output for a specific pipeline run.

    Args:
        run_id: Unique pipeline execution identifier (e.g. 'RUN-20261011-1e1063ed')

    Returns:
        Complete log text content or descriptive error message if missing.
    """
    run_id = str(run_id).strip()
    log_file = LOGS_DIR / f"pipeline_{run_id}.log"

    if not log_file.exists():
        # Fallback search if partial run_id was provided
        matches = list(LOGS_DIR.glob(f"*{run_id}*.log"))
        if matches:
            log_file = matches[0]
        else:
            return f"[ERROR] No log file found for run_id '{run_id}' in {LOGS_DIR}."

    try:
        content = log_file.read_text(encoding="utf-8")
        if not content.strip():
            return f"[WARNING] Log file for run_id '{run_id}' is empty."
        return content
    except Exception as e:
        return f"[ERROR] Failed reading log file {log_file.name}: {str(e)}"


def get_run_metadata(run_id: str) -> Dict[str, Any]:
    """
    Fetches execution metadata for a specific pipeline run from metadata/runs.jsonl.
    Also supplements with bronze snapshot schema details if available.

    Args:
        run_id: Unique pipeline execution identifier.

    Returns:
        Dictionary containing run status, timestamps, failure reasons, and inputs.
    """
    run_id = str(run_id).strip()
    runs_file = METADATA_DIR / "runs.jsonl"

    if not runs_file.exists():
        return {"error": f"Metadata repository {runs_file} does not exist."}

    matched_run: Optional[Dict[str, Any]] = None

    try:
        with open(runs_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                if record.get("run_id") == run_id:
                    matched_run = record
                    break
    except Exception as e:
        return {"error": f"Failed reading {runs_file.name}: {str(e)}"}

    if not matched_run:
        return {"error": f"Run metadata not found for run_id '{run_id}'."}

    # Enrich with snapshot info if available
    snapshot_file = METADATA_DIR / f"bronze_snapshot_{run_id}.json"
    if snapshot_file.exists():
        try:
            snapshot_data = json.loads(snapshot_file.read_text(encoding="utf-8"))
            matched_run["bronze_columns"] = snapshot_data.get("columns", [])
            matched_run["bronze_record_count"] = snapshot_data.get("record_count", 0)
        except Exception:
            pass

    return matched_run


def get_previous_run_info(run_id: str) -> Dict[str, Any]:
    """
    Fetches information about the run executed immediately prior to the specified run_id.
    Useful for detecting schema drift, column changes, or behavioral regressions.

    Args:
        run_id: Unique pipeline execution identifier to compare against.

    Returns:
        Dictionary containing preceding run details, or message if no predecessor exists.
    """
    run_id = str(run_id).strip()
    runs_file = METADATA_DIR / "runs.jsonl"

    if not runs_file.exists():
        return {"error": f"Runs file {runs_file} does not exist."}

    runs: List[Dict[str, Any]] = []
    try:
        with open(runs_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    runs.append(json.loads(line))
    except Exception as e:
        return {"error": f"Failed reading {runs_file}: {str(e)}"}

    # Sort runs chronologically by timestamp
    runs.sort(key=lambda x: x.get("timestamp", ""))

    target_index = -1
    for idx, r in enumerate(runs):
        if r.get("run_id") == run_id:
            target_index = idx
            break

    if target_index == -1:
        # If run_id not in list, return the latest run in history
        if runs:
            latest = runs[-1]
            return {
                "message": f"Run '{run_id}' was not found; returning latest known run in history.",
                "previous_run": latest,
            }
        return {"error": f"No runs recorded in history."}

    if target_index == 0:
        return {
            "message": f"Run '{run_id}' is the earliest recorded run. No previous run exists.",
            "is_initial_run": True,
        }

    previous_run = runs[target_index - 1]

    # Also check if predecessor has a bronze snapshot to include its columns
    prev_run_id = previous_run.get("run_id")
    if prev_run_id:
        prev_snapshot = METADATA_DIR / f"bronze_snapshot_{prev_run_id}.json"
        if prev_snapshot.exists():
            try:
                data = json.loads(prev_snapshot.read_text(encoding="utf-8"))
                previous_run["bronze_columns"] = data.get("columns", [])
            except Exception:
                pass

    return {
        "target_run_id": run_id,
        "previous_run_id": prev_run_id,
        "previous_run": previous_run,
    }


def search_runbooks(query: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """
    Searches operational runbooks using the hybrid RAG RunbookRetriever.

    Args:
        query: Symptom, failure message, or error keyword to search.
        top_k: Number of relevant sections to retrieve.

    Returns:
        List of matching runbook sections with remediation suggestions and relevance scores.
    """
    retriever = _get_retriever()
    results = retriever.search(query=query, top_k=top_k)
    return results


# ---------------- OpenAI Tool Calling Specifications ----------------

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_pipeline_logs",
            "description": "Fetches the full execution log for a given pipeline run_id, revealing exact DQ errors and stack traces.",
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id": {
                        "type": "string",
                        "description": "Unique pipeline execution identifier (e.g. 'RUN-20261011-1e1063ed')."
                    }
                },
                "required": ["run_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_run_metadata",
            "description": "Fetches execution metadata for a pipeline run, including record counts, timestamps, failure reasons, and inputs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id": {
                        "type": "string",
                        "description": "Unique pipeline execution identifier to look up."
                    }
                },
                "required": ["run_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_previous_run_info",
            "description": "Fetches the previous pipeline run that executed before the target run_id to compare schemas, records, and baselines.",
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id": {
                        "type": "string",
                        "description": "The current run_id to find the predecessor for."
                    }
                },
                "required": ["run_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_runbooks",
            "description": "Searches data reliability runbooks for diagnostic procedures and recommended remediation actions for specific errors.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Error message, failure category, or symptom to search for (e.g. 'missing country column', 'duplicate customer_id')."
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Maximum number of runbook chunks to retrieve (default: 3).",
                        "default": 3
                    }
                },
                "required": ["query"]
            }
        }
    }
]

TOOL_REGISTRY = {
    "get_pipeline_logs": get_pipeline_logs,
    "get_run_metadata": get_run_metadata,
    "get_previous_run_info": get_previous_run_info,
    "search_runbooks": search_runbooks,
}


def execute_tool(name: str, arguments: Dict[str, Any]) -> Any:
    """Dispatches and safely executes an evidence tool by name."""
    if name not in TOOL_REGISTRY:
        return f"[ERROR] Tool '{name}' is not recognized. Allowed tools: {list(TOOL_REGISTRY.keys())}"

    tool_fn = TOOL_REGISTRY[name]
    try:
        return tool_fn(**arguments)
    except TypeError as e:
        return f"[ERROR] Invalid arguments for tool '{name}': {str(e)}"
    except Exception as e:
        return f"[ERROR] Execution failed for tool '{name}': {str(e)}"
