"""
Root Cause Analysis (RCA) Agent.

Uses Claude Opus 5 with tool-calling to:
  1. Retrieve incident details and metric timeline
  2. Query correlated logs and transaction failures
  3. Identify root causes and contributing factors
  4. Persist the RCA to the Gold layer

All tool functions are marked with @tool.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any

import anthropic
from sqlalchemy import select

from src.agents.base_agent import tool, BaseAgent
from src.database.connection import get_db
from src.database.models import (
    GoldIncident, GoldRCA, SilverMetric, SilverLog, SilverTransaction
)
from config.settings import settings


# ─────────────────────────── TOOL FUNCTIONS ──────────────────────────────────

@tool(
    description="Retrieve full details of a specific incident from the Gold layer.",
    schema={
        "type": "object",
        "properties": {
            "incident_id": {"type": "string", "description": "The incident ID, e.g. INC-XXXXXXXX"},
        },
        "required": ["incident_id"],
    },
)
def get_incident_details(incident_id: str) -> Dict:
    """Returns full details of a Gold-layer incident."""
    with get_db() as db:
        row = db.execute(
            select(GoldIncident).where(GoldIncident.incident_id == incident_id)
        ).scalar_one_or_none()
        if not row:
            return {"error": f"Incident {incident_id} not found"}
        return {
            "incident_id": row.incident_id,
            "title": row.title,
            "severity": row.severity,
            "service": row.service,
            "incident_type": row.incident_type,
            "status": row.status,
            "detected_at": row.detected_at.isoformat() if row.detected_at else None,
            "anomaly_details": row.anomaly_details,
            "ai_classification": row.ai_classification,
        }


@tool(
    description="Get the metric time series around the incident window to identify the anomaly pattern.",
    schema={
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "Service name"},
            "start_time": {"type": "string", "description": "ISO datetime for window start"},
            "end_time": {"type": "string", "description": "ISO datetime for window end"},
        },
        "required": ["service", "start_time", "end_time"],
    },
)
def get_metric_timeline(service: str, start_time: str, end_time: str) -> List[Dict]:
    """Returns metric timeline for a service between two timestamps."""
    try:
        start = datetime.fromisoformat(start_time)
        end = datetime.fromisoformat(end_time)
    except Exception:
        start = datetime.utcnow() - timedelta(hours=3)
        end = datetime.utcnow()

    with get_db() as db:
        rows = db.execute(
            select(SilverMetric)
            .where(
                SilverMetric.service == service,
                SilverMetric.timestamp >= start,
                SilverMetric.timestamp <= end,
            )
            .order_by(SilverMetric.timestamp)
            .limit(200)
        ).scalars().all()
        return [
            {
                "timestamp": r.timestamp.isoformat(),
                "avg_latency_ms": r.avg_latency_ms,
                "cpu_usage": r.cpu_usage,
                "error_rate": r.error_rate,
                "request_count": r.request_count,
                "is_anomaly": r.is_anomaly,
                "anomaly_type": r.anomaly_type,
            }
            for r in rows
        ]


@tool(
    description="Query error logs during the incident window to find error patterns and messages.",
    schema={
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "Service name"},
            "start_time": {"type": "string", "description": "ISO datetime for window start"},
            "end_time": {"type": "string", "description": "ISO datetime for window end"},
            "limit": {"type": "integer", "description": "Maximum log entries to return"},
        },
        "required": ["service", "start_time", "end_time"],
    },
)
def get_incident_logs(service: str, start_time: str, end_time: str, limit: int = 100) -> List[Dict]:
    """Returns error and warning logs during the incident window."""
    try:
        start = datetime.fromisoformat(start_time)
        end = datetime.fromisoformat(end_time)
    except Exception:
        start = datetime.utcnow() - timedelta(hours=3)
        end = datetime.utcnow()

    with get_db() as db:
        rows = db.execute(
            select(SilverLog)
            .where(
                SilverLog.service == service,
                SilverLog.timestamp >= start,
                SilverLog.timestamp <= end,
                SilverLog.is_error == True,
            )
            .order_by(SilverLog.timestamp.desc())
            .limit(limit)
        ).scalars().all()
        return [
            {
                "timestamp": r.timestamp.isoformat(),
                "level": r.level,
                "message": r.message,
                "endpoint": r.endpoint,
                "status_code": r.status_code,
                "latency_ms": r.latency_ms,
                "error_category": r.error_category,
            }
            for r in rows
        ]


@tool(
    description="Get payment transaction failure statistics during the incident window.",
    schema={
        "type": "object",
        "properties": {
            "start_time": {"type": "string", "description": "ISO datetime start"},
            "end_time": {"type": "string", "description": "ISO datetime end"},
        },
        "required": ["start_time", "end_time"],
    },
)
def get_transaction_failures(start_time: str, end_time: str) -> Dict:
    """Returns transaction failure summary for the incident window."""
    try:
        start = datetime.fromisoformat(start_time)
        end = datetime.fromisoformat(end_time)
    except Exception:
        start = datetime.utcnow() - timedelta(hours=3)
        end = datetime.utcnow()

    with get_db() as db:
        rows = db.execute(
            select(SilverTransaction).where(
                SilverTransaction.timestamp >= start,
                SilverTransaction.timestamp <= end,
            )
        ).scalars().all()

        total = len(rows)
        failed = [r for r in rows if r.is_failed]
        reasons = {}
        for r in failed:
            reason = r.failure_reason or "unknown"
            reasons[reason] = reasons.get(reason, 0) + 1

        return {
            "total_transactions": total,
            "failed_transactions": len(failed),
            "failure_rate": round(len(failed) / total, 4) if total > 0 else 0,
            "failure_reasons": reasons,
        }


@tool(
    description="Check if other services have correlated anomalies during the same window (dependency analysis).",
    schema={
        "type": "object",
        "properties": {
            "start_time": {"type": "string", "description": "ISO datetime start"},
            "end_time": {"type": "string", "description": "ISO datetime end"},
            "exclude_service": {"type": "string", "description": "Primary incident service to exclude from results"},
        },
        "required": ["start_time", "end_time"],
    },
)
def get_correlated_services(start_time: str, end_time: str, exclude_service: str = "") -> List[Dict]:
    """Finds other services with anomalies in the same time window — helps identify cascading failures."""
    try:
        start = datetime.fromisoformat(start_time)
        end = datetime.fromisoformat(end_time)
    except Exception:
        start = datetime.utcnow() - timedelta(hours=3)
        end = datetime.utcnow()

    with get_db() as db:
        q = select(SilverMetric).where(
            SilverMetric.is_anomaly == True,
            SilverMetric.timestamp >= start,
            SilverMetric.timestamp <= end,
        )
        if exclude_service:
            q = q.where(SilverMetric.service != exclude_service)

        rows = db.execute(q).scalars().all()

        by_service: Dict[str, List] = {}
        for r in rows:
            by_service.setdefault(r.service, []).append(r)

        return [
            {
                "service": svc,
                "anomaly_count": len(recs),
                "anomaly_types": list({r.anomaly_type for r in recs if r.anomaly_type}),
            }
            for svc, recs in by_service.items()
        ]


@tool(
    description="Save the completed Root Cause Analysis to the Gold layer.",
    schema={
        "type": "object",
        "properties": {
            "incident_id": {"type": "string", "description": "Incident ID being analysed"},
            "root_cause": {"type": "string", "description": "Primary root cause identified"},
            "contributing_factors": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of contributing factors",
            },
            "affected_services": {
                "type": "array",
                "items": {"type": "string"},
                "description": "All affected services",
            },
            "timeline": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Chronological list of events [{time, event}]",
            },
            "confidence_score": {"type": "number", "description": "Confidence 0.0–1.0"},
            "ai_analysis": {"type": "string", "description": "Full AI narrative analysis"},
        },
        "required": ["incident_id", "root_cause", "confidence_score", "ai_analysis"],
    },
)
def save_rca(
    incident_id: str,
    root_cause: str,
    confidence_score: float,
    ai_analysis: str,
    contributing_factors: List[str] = None,
    affected_services: List[str] = None,
    timeline: List[Dict] = None,
) -> Dict:
    """Persists the RCA to the Gold layer and updates the incident status."""
    rca = GoldRCA(
        incident_id=incident_id,
        root_cause=root_cause,
        contributing_factors=contributing_factors or [],
        affected_services=affected_services or [],
        timeline=timeline or [],
        confidence_score=confidence_score,
        ai_analysis=ai_analysis,
    )
    with get_db() as db:
        db.add(rca)
        # Update incident status
        incident = db.execute(
            select(GoldIncident).where(GoldIncident.incident_id == incident_id)
        ).scalar_one_or_none()
        if incident:
            incident.status = "investigating"

    return {"status": "saved", "incident_id": incident_id, "confidence_score": confidence_score}


# ─────────────────────────── AGENT CLASS ─────────────────────────────────────

SYSTEM_PROMPT = """You are an AIOps Root Cause Analysis Agent for an e-commerce platform.

Your job is to:
1. Retrieve incident details and the metric timeline around it
2. Analyse error logs to find patterns (repeated exceptions, timeouts, cascade failures)
3. Check for correlated anomalies in dependent services
4. Check transaction failure data if the incident involves payments
5. Identify the single most probable root cause and contributing factors
6. Build a chronological timeline of events
7. Save a complete RCA with confidence score to the Gold layer

Be specific and technical. Reference actual metrics, log messages, and timestamps.
Always save the RCA before finishing."""


class RCAAgent(BaseAgent):
    def __init__(self, client: anthropic.Anthropic):
        super().__init__(
            client=client,
            model=settings.claude_model,
            tool_names=[
                "get_incident_details",
                "get_metric_timeline",
                "get_incident_logs",
                "get_transaction_failures",
                "get_correlated_services",
                "save_rca",
            ],
        )

    def analyse(self, incident_id: str) -> str:
        user_prompt = (
            f"Perform a thorough Root Cause Analysis for incident {incident_id}. "
            "Use all available tools to gather metric timelines, error logs, "
            "and correlated service data. Identify the root cause, contributing factors, "
            "build a timeline, assign a confidence score, and save the RCA."
        )
        result = self.run(SYSTEM_PROMPT, user_prompt, max_iterations=30)
        print(f"  [RCAAgent] RCA complete for {incident_id}")
        return result
