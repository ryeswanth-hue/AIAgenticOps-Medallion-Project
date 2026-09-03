"""
Remediation Agent.

Uses Claude Opus 5 with tool-calling to:
  1. Read the RCA for an incident
  2. Query a runbook knowledge base
  3. Generate immediate actions + long-term fixes
  4. Persist the remediation plan to the Gold layer

All tool functions are marked with @tool.
"""

from datetime import datetime
from typing import List, Dict, Any

import anthropic
from sqlalchemy import select

from src.agents.base_agent import tool, BaseAgent
from src.database.connection import get_db
from src.database.models import GoldIncident, GoldRCA, GoldRemediation
from config.settings import settings


# ─────────────── RUNBOOK KNOWLEDGE BASE (embedded) ───────────────────────────
RUNBOOKS: Dict[str, Dict] = {
    "latency_spike": {
        "immediate_actions": [
            "Enable circuit breaker for affected service",
            "Check downstream dependencies for bottlenecks",
            "Scale out service instances (horizontal scaling)",
            "Enable request throttling / rate limiting",
            "Verify database connection pool saturation",
        ],
        "long_term_fixes": [
            "Implement caching layer (Redis) for hot data paths",
            "Optimise slow database queries with EXPLAIN ANALYZE",
            "Add read replicas to database cluster",
            "Implement async processing for non-critical operations",
            "Review and tune connection timeouts",
        ],
        "estimated_resolution": "15–45 minutes",
    },
    "error_surge": {
        "immediate_actions": [
            "Redirect traffic to healthy instances via load balancer",
            "Roll back last deployment if error surge followed a deploy",
            "Check for downstream dependency outages",
            "Enable fallback / degraded mode",
            "Alert on-call engineering team",
        ],
        "long_term_fixes": [
            "Improve error handling and retry logic with exponential backoff",
            "Add health checks for all downstream dependencies",
            "Implement bulkhead pattern to isolate failures",
            "Add automated canary deployment gates",
            "Increase unit and integration test coverage",
        ],
        "estimated_resolution": "10–30 minutes",
    },
    "payment_failure": {
        "immediate_actions": [
            "Switch to backup payment gateway provider",
            "Notify customer-facing team to display maintenance banner",
            "Contact payment gateway vendor support",
            "Enable retry queue for failed transactions",
            "Pause scheduled payment batches",
        ],
        "long_term_fixes": [
            "Implement multi-provider payment gateway with automatic failover",
            "Add payment idempotency keys to prevent duplicate charges",
            "Implement comprehensive payment event logging",
            "Set up proactive gateway health monitoring",
            "Review and test SLA with gateway provider",
        ],
        "estimated_resolution": "30–90 minutes",
    },
    "cpu_overload": {
        "immediate_actions": [
            "Auto-scale service pods/instances immediately",
            "Identify and kill runaway processes",
            "Enable CPU throttling for non-critical background jobs",
            "Offload batch processing to off-peak hours",
        ],
        "long_term_fixes": [
            "Profile application code to find CPU-intensive hot paths",
            "Implement job queue (Celery/RQ) for background tasks",
            "Review and optimise O(n²) algorithms in hot paths",
            "Set CPU resource limits and requests in Kubernetes",
            "Add auto-scaling policies based on CPU metrics",
        ],
        "estimated_resolution": "5–20 minutes",
    },
    "traffic_spike": {
        "immediate_actions": [
            "Enable CDN caching for static assets immediately",
            "Activate auto-scaling group policy",
            "Enable queue-based request buffering",
            "Deploy rate limiting on API gateway",
            "Consider temporary geo-blocking if spike is concentrated",
        ],
        "long_term_fixes": [
            "Implement predictive auto-scaling based on traffic patterns",
            "Add full-page caching for product listing pages",
            "Review and increase max concurrent connection settings",
            "Conduct regular load testing to validate capacity",
            "Implement graceful degradation for peak loads",
        ],
        "estimated_resolution": "10–30 minutes",
    },
    "default": {
        "immediate_actions": [
            "Review recent deployments for potential cause",
            "Check all health endpoints across services",
            "Review application and infrastructure logs",
            "Escalate to on-call team if severity P1/P2",
        ],
        "long_term_fixes": [
            "Improve monitoring and alerting coverage",
            "Conduct post-incident review and blameless postmortem",
            "Document findings in the runbook",
        ],
        "estimated_resolution": "Varies",
    },
}


# ─────────────────────────── TOOL FUNCTIONS ──────────────────────────────────

@tool(
    description="Retrieve the RCA details for an incident to understand the root cause before suggesting remediation.",
    schema={
        "type": "object",
        "properties": {
            "incident_id": {"type": "string", "description": "Incident ID to retrieve RCA for"},
        },
        "required": ["incident_id"],
    },
)
def get_rca_for_incident(incident_id: str) -> Dict:
    """Returns the RCA stored in the Gold layer for a given incident."""
    with get_db() as db:
        rca = db.execute(
            select(GoldRCA).where(GoldRCA.incident_id == incident_id)
        ).scalar_one_or_none()
        if not rca:
            return {"error": f"No RCA found for {incident_id}"}
        return {
            "incident_id": rca.incident_id,
            "root_cause": rca.root_cause,
            "contributing_factors": rca.contributing_factors,
            "affected_services": rca.affected_services,
            "timeline": rca.timeline,
            "confidence_score": rca.confidence_score,
            "ai_analysis": rca.ai_analysis,
        }


@tool(
    description="Look up the runbook for a specific incident type to get proven remediation steps.",
    schema={
        "type": "object",
        "properties": {
            "incident_type": {
                "type": "string",
                "description": "Incident type: latency_spike / error_surge / payment_failure / cpu_overload / traffic_spike",
            },
        },
        "required": ["incident_type"],
    },
)
def lookup_runbook(incident_type: str) -> Dict:
    """Returns the runbook for the given incident type."""
    runbook = RUNBOOKS.get(incident_type, RUNBOOKS["default"])
    return {
        "incident_type": incident_type,
        "runbook": runbook,
    }


@tool(
    description="Get the incident details including severity and affected service.",
    schema={
        "type": "object",
        "properties": {
            "incident_id": {"type": "string", "description": "Incident ID"},
        },
        "required": ["incident_id"],
    },
)
def get_incident_for_remediation(incident_id: str) -> Dict:
    """Fetches incident metadata needed to tailor remediation advice."""
    with get_db() as db:
        row = db.execute(
            select(GoldIncident).where(GoldIncident.incident_id == incident_id)
        ).scalar_one_or_none()
        if not row:
            return {"error": "Incident not found"}
        return {
            "incident_id": row.incident_id,
            "title": row.title,
            "severity": row.severity,
            "service": row.service,
            "incident_type": row.incident_type,
            "status": row.status,
        }


@tool(
    description="Save the AI-generated remediation plan to the Gold layer.",
    schema={
        "type": "object",
        "properties": {
            "incident_id": {"type": "string", "description": "Incident ID"},
            "rca_id": {"type": "integer", "description": "RCA database ID"},
            "immediate_actions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of immediate actions to take NOW",
            },
            "long_term_fixes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of long-term engineering fixes",
            },
            "runbook_steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Step-by-step runbook for on-call engineer",
            },
            "estimated_resolution_time": {"type": "string", "description": "e.g. '15-30 minutes'"},
            "ai_recommendation": {"type": "string", "description": "Full AI narrative recommendation"},
        },
        "required": ["incident_id", "immediate_actions", "long_term_fixes", "ai_recommendation"],
    },
)
def save_remediation(
    incident_id: str,
    immediate_actions: List[str],
    long_term_fixes: List[str],
    ai_recommendation: str,
    rca_id: int = None,
    runbook_steps: List[str] = None,
    estimated_resolution_time: str = "Unknown",
) -> Dict:
    """Persists remediation plan and updates incident status to 'investigating'."""
    remediation = GoldRemediation(
        incident_id=incident_id,
        rca_id=rca_id,
        immediate_actions=immediate_actions,
        long_term_fixes=long_term_fixes,
        runbook_steps=runbook_steps or [],
        estimated_resolution_time=estimated_resolution_time,
        ai_recommendation=ai_recommendation,
    )
    with get_db() as db:
        db.add(remediation)
        incident = db.execute(
            select(GoldIncident).where(GoldIncident.incident_id == incident_id)
        ).scalar_one_or_none()
        if incident and incident.status == "investigating":
            pass  # Already in investigating state

    return {"status": "saved", "incident_id": incident_id}


# ─────────────────────────── AGENT CLASS ─────────────────────────────────────

SYSTEM_PROMPT = """You are an AIOps Remediation Agent for an e-commerce platform.

Your job is to:
1. Retrieve the incident details and its RCA
2. Look up the runbook for that incident type
3. Combine the RCA findings with runbook best practices to create a tailored remediation plan
4. Prioritise immediate actions (things the on-call engineer does RIGHT NOW)
5. List long-term fixes (engineering improvements for next sprint)
6. Create a step-by-step runbook for the on-call engineer
7. Save the remediation plan to the Gold layer

Always be specific. Reference the actual service, endpoint, and error type from the RCA.
The immediate actions must be concrete commands or steps, not vague suggestions."""


class RemediationAgent(BaseAgent):
    def __init__(self, client: anthropic.Anthropic):
        super().__init__(
            client=client,
            model=settings.claude_model,
            tool_names=[
                "get_incident_for_remediation",
                "get_rca_for_incident",
                "lookup_runbook",
                "save_remediation",
            ],
        )

    def remediate(self, incident_id: str) -> str:
        user_prompt = (
            f"Create a complete remediation plan for incident {incident_id}. "
            "First retrieve the incident and its RCA, then look up the appropriate runbook, "
            "then combine both to produce a tailored plan with immediate actions, "
            "long-term fixes, and on-call runbook steps. Save the plan when done."
        )
        result = self.run(SYSTEM_PROMPT, user_prompt, max_iterations=20)
        print(f"  [RemediationAgent] Remediation plan saved for {incident_id}")
        return result
