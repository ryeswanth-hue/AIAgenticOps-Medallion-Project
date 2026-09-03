"""
Orchestrator Agent.

Top-level agent that coordinates the full AIOps pipeline:
  1. Triggers IncidentDetectionAgent → finds and classifies incidents
  2. For each P1/P2 incident → triggers RCAAgent
  3. For each incident with RCA → triggers RemediationAgent
  4. Triggers ReportAgent → generates final HTML dashboard

The orchestrator itself is also an agent with @tool decorated functions
that it uses to query pipeline state and delegate to sub-agents.
"""

import json
from datetime import datetime
from typing import List, Dict

import anthropic
from sqlalchemy import select

from src.agents.base_agent import tool, BaseAgent
from src.agents.incident_detection_agent import IncidentDetectionAgent
from src.agents.rca_agent import RCAAgent
from src.agents.remediation_agent import RemediationAgent
from src.agents.report_agent import ReportAgent
from src.database.connection import get_db
from src.database.models import GoldIncident, GoldRCA, GoldRemediation
from config.settings import settings


# ─────────────────────────── TOOL FUNCTIONS ──────────────────────────────────

@tool(
    description="Run the Incident Detection Agent to scan for new incidents.",
    schema={"type": "object", "properties": {}, "required": []},
)
def run_incident_detection() -> Dict:
    """Launches the IncidentDetectionAgent and returns its result summary."""
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    agent = IncidentDetectionAgent(client)
    result = agent.detect()
    return {"status": "completed", "summary": result[:2000]}


@tool(
    description="Run the RCA Agent for a specific incident to identify root cause.",
    schema={
        "type": "object",
        "properties": {
            "incident_id": {"type": "string", "description": "Incident ID to analyse"},
        },
        "required": ["incident_id"],
    },
)
def run_rca_analysis(incident_id: str) -> Dict:
    """Launches the RCAAgent for the given incident and returns result."""
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    agent = RCAAgent(client)
    result = agent.analyse(incident_id)
    return {"status": "completed", "incident_id": incident_id, "summary": result[:2000]}


@tool(
    description="Run the Remediation Agent for a specific incident after its RCA is complete.",
    schema={
        "type": "object",
        "properties": {
            "incident_id": {"type": "string", "description": "Incident ID to remediate"},
        },
        "required": ["incident_id"],
    },
)
def run_remediation(incident_id: str) -> Dict:
    """Launches the RemediationAgent and returns result."""
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    agent = RemediationAgent(client)
    result = agent.remediate(incident_id)
    return {"status": "completed", "incident_id": incident_id, "summary": result[:1000]}


@tool(
    description="Run the Report Agent to generate the final HTML dashboard report.",
    schema={"type": "object", "properties": {}, "required": []},
)
def run_report_generation() -> Dict:
    """Launches the ReportAgent and generates the HTML report."""
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    agent = ReportAgent(client)
    result = agent.generate()
    return {"status": "completed", "summary": result[:1000]}


@tool(
    description="List all open incidents from the Gold layer that still need RCA or remediation.",
    schema={
        "type": "object",
        "properties": {
            "severity_filter": {"type": "string", "description": "P1 / P2 / all"},
        },
        "required": [],
    },
)
def list_pending_incidents(severity_filter: str = "all") -> List[Dict]:
    """Returns incidents without completed RCA or remediation."""
    with get_db() as db:
        q = select(GoldIncident).where(GoldIncident.status.in_(["open", "investigating"]))
        if severity_filter != "all":
            q = q.where(GoldIncident.severity == severity_filter)
        incidents = db.execute(q).scalars().all()

        rca_done = set(
            r[0] for r in db.execute(select(GoldRCA.incident_id)).all()
        )
        remediation_done = set(
            r[0] for r in db.execute(select(GoldRemediation.incident_id)).all()
        )

        return [
            {
                "incident_id": inc.incident_id,
                "severity": inc.severity,
                "service": inc.service,
                "incident_type": inc.incident_type,
                "has_rca": inc.incident_id in rca_done,
                "has_remediation": inc.incident_id in remediation_done,
            }
            for inc in incidents
        ]


@tool(
    description="Get the current pipeline status: incident count, RCA coverage, remediation coverage.",
    schema={"type": "object", "properties": {}, "required": []},
)
def get_pipeline_status() -> Dict:
    """Returns a summary of pipeline completion across all layers."""
    with get_db() as db:
        incident_count = db.execute(select(GoldIncident)).scalars().all()
        rca_count = len(db.execute(select(GoldRCA)).scalars().all())
        remediation_count = len(db.execute(select(GoldRemediation)).scalars().all())
        total = len(incident_count)
        p1_open = sum(1 for i in incident_count if i.severity == "P1" and i.status != "resolved")
        p2_open = sum(1 for i in incident_count if i.severity == "P2" and i.status != "resolved")

        return {
            "total_incidents": total,
            "p1_open": p1_open,
            "p2_open": p2_open,
            "rca_completed": rca_count,
            "remediation_completed": remediation_count,
            "rca_coverage_pct": round(rca_count / total * 100, 1) if total > 0 else 0,
            "remediation_coverage_pct": round(remediation_count / total * 100, 1) if total > 0 else 0,
        }


# ─────────────────────────── ORCHESTRATOR CLASS ──────────────────────────────

SYSTEM_PROMPT = """You are the AIOps Orchestrator Agent for an e-commerce platform.

You coordinate a multi-agent pipeline:
  1. IncidentDetectionAgent — scans Silver layer anomalies and creates Gold incidents
  2. RCAAgent — performs root cause analysis for each incident
  3. RemediationAgent — generates remediation plans from RCA findings
  4. ReportAgent — generates the final HTML dashboard

Your execution order:
  Step 1: Run incident detection to find all new incidents
  Step 2: Check list of pending incidents
  Step 3: For each P1 or P2 incident without an RCA — run RCA analysis
  Step 4: For each incident with an RCA but no remediation — run remediation
  Step 5: Check pipeline status to confirm coverage
  Step 6: Run report generation as the final step

Be systematic. Don't skip steps. Run sub-agents in logical order.
At the end, report the final pipeline status and the report file path."""


class OrchestratorAgent(BaseAgent):
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        super().__init__(
            client=self.client,
            model=settings.claude_model,
            tool_names=[
                "run_incident_detection",
                "list_pending_incidents",
                "run_rca_analysis",
                "run_remediation",
                "run_report_generation",
                "get_pipeline_status",
            ],
        )

    def run_pipeline(self) -> str:
        """Executes the full AIOps pipeline end-to-end."""
        print("\n" + "=" * 60)
        print("  ORCHESTRATOR: Starting AIOps pipeline...")
        print("=" * 60)
        user_prompt = (
            "Execute the full AIOps pipeline:\n"
            "1. Detect incidents in Silver layer data\n"
            "2. Run RCA for all P1 and P2 incidents\n"
            "3. Generate remediation plans for incidents with RCA\n"
            "4. Generate the final HTML report\n"
            "Report final pipeline status and report location."
        )
        result = self.run(SYSTEM_PROMPT, user_prompt, max_iterations=40)
        print("\n" + "=" * 60)
        print("  ORCHESTRATOR: Pipeline complete.")
        print("=" * 60)
        return result
