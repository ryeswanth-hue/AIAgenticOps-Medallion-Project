"""
Incident Detection Agent.

Uses Claude Opus 5 with tool-calling to:
  1. Query Silver-layer anomalies
  2. Classify whether each anomaly constitutes a real incident
  3. Enrich and store incidents in the Gold layer

All tool functions are marked with @tool.
"""

import json
from datetime import datetime, timedelta
from typing import List, Dict, Any

import anthropic
from sqlalchemy import select, func

from src.agents.base_agent import tool, BaseAgent
from src.database.connection import get_db
from src.database.models import SilverMetric, SilverLog, GoldIncident
from config.settings import settings


# ─────────────────────────── TOOL FUNCTIONS ──────────────────────────────────

@tool(
    description="Query recent anomalous metrics from the Silver layer for a given service and time window.",
    schema={
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "Service name, e.g. 'payment-service'. Use 'all' for all services."},
            "minutes": {"type": "integer", "description": "Look-back window in minutes (default 60)"},
        },
        "required": [],
    },
)
def query_silver_anomalies(service: str = "all", minutes: int = 60) -> List[Dict]:
    """Returns anomalous Silver metric records within the look-back window."""
    cutoff = datetime.utcnow() - timedelta(minutes=minutes)
    with get_db() as db:
        q = select(SilverMetric).where(
            SilverMetric.is_anomaly == True,
            SilverMetric.timestamp >= cutoff,
        )
        if service != "all":
            q = q.where(SilverMetric.service == service)
        rows = db.execute(q.order_by(SilverMetric.timestamp.desc()).limit(100)).scalars().all()
        return [
            {
                "id": r.id,
                "service": r.service,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "anomaly_type": r.anomaly_type,
                "avg_latency_ms": r.avg_latency_ms,
                "cpu_usage": r.cpu_usage,
                "error_rate": r.error_rate,
                "latency_zscore": r.latency_zscore,
                "cpu_zscore": r.cpu_zscore,
                "error_rate_zscore": r.error_rate_zscore,
            }
            for r in rows
        ]


@tool(
    description="Get a summary of recent error logs from the Silver layer to correlate with anomalies.",
    schema={
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "Service name or 'all'"},
            "minutes": {"type": "integer", "description": "Look-back window in minutes"},
            "limit": {"type": "integer", "description": "Max log records to return"},
        },
        "required": [],
    },
)
def query_error_logs(service: str = "all", minutes: int = 60, limit: int = 50) -> List[Dict]:
    """Returns recent error logs from the Silver layer."""
    cutoff = datetime.utcnow() - timedelta(minutes=minutes)
    with get_db() as db:
        q = select(SilverLog).where(
            SilverLog.is_error == True,
            SilverLog.timestamp >= cutoff,
        )
        if service != "all":
            q = q.where(SilverLog.service == service)
        rows = db.execute(q.order_by(SilverLog.timestamp.desc()).limit(limit)).scalars().all()
        return [
            {
                "service": r.service,
                "level": r.level,
                "message": r.message,
                "endpoint": r.endpoint,
                "status_code": r.status_code,
                "latency_ms": r.latency_ms,
                "error_category": r.error_category,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            }
            for r in rows
        ]


@tool(
    description="Get all open incidents in the Gold layer to avoid creating duplicate incidents.",
    schema={
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "Filter by service or 'all'"},
        },
        "required": [],
    },
)
def get_open_incidents(service: str = "all") -> List[Dict]:
    """Returns currently open Gold-layer incidents."""
    with get_db() as db:
        q = select(GoldIncident).where(GoldIncident.status == "open")
        if service != "all":
            q = q.where(GoldIncident.service == service)
        rows = db.execute(q).scalars().all()
        return [
            {
                "incident_id": r.incident_id,
                "title": r.title,
                "severity": r.severity,
                "service": r.service,
                "incident_type": r.incident_type,
                "detected_at": r.detected_at.isoformat() if r.detected_at else None,
            }
            for r in rows
        ]


@tool(
    description="Create a confirmed incident in the Gold layer after AI verification.",
    schema={
        "type": "object",
        "properties": {
            "incident_id": {"type": "string", "description": "Unique incident ID (e.g. INC-XXXXXXXX)"},
            "title": {"type": "string", "description": "Short incident title"},
            "severity": {"type": "string", "description": "P1, P2, P3, or P4"},
            "service": {"type": "string", "description": "Affected service name"},
            "incident_type": {"type": "string", "description": "latency_spike / error_surge / payment_failure / cpu_overload / traffic_spike"},
            "ai_classification": {"type": "string", "description": "AI reasoning for classification"},
            "anomaly_details": {"type": "object", "description": "Anomaly metrics summary"},
        },
        "required": ["incident_id", "title", "severity", "service", "incident_type", "ai_classification"],
    },
)
def create_incident(
    incident_id: str,
    title: str,
    severity: str,
    service: str,
    incident_type: str,
    ai_classification: str,
    anomaly_details: dict = None,
) -> Dict:
    """Persists a confirmed incident to the Gold layer."""
    incident = GoldIncident(
        incident_id=incident_id,
        title=title,
        severity=severity,
        status="open",
        service=service,
        incident_type=incident_type,
        detected_at=datetime.utcnow(),
        ai_classification=ai_classification,
        anomaly_details=anomaly_details or {},
    )
    with get_db() as db:
        existing = db.execute(
            select(GoldIncident).where(GoldIncident.incident_id == incident_id)
        ).scalar_one_or_none()
        if existing:
            return {"status": "skipped", "reason": "incident already exists", "incident_id": incident_id}
        db.add(incident)
    return {"status": "created", "incident_id": incident_id, "severity": severity}


@tool(
    description="Get metric statistics summary for a service: mean, max, std of latency/CPU/error_rate.",
    schema={
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "Service name"},
            "minutes": {"type": "integer", "description": "Look-back window in minutes"},
        },
        "required": ["service"],
    },
)
def get_service_metric_summary(service: str, minutes: int = 120) -> Dict:
    """Returns statistical summary of a service's metrics."""
    cutoff = datetime.utcnow() - timedelta(minutes=minutes)
    with get_db() as db:
        rows = db.execute(
            select(SilverMetric).where(
                SilverMetric.service == service,
                SilverMetric.timestamp >= cutoff,
            )
        ).scalars().all()

        if not rows:
            return {"error": "no data found"}

        import numpy as np
        latencies = [r.avg_latency_ms for r in rows]
        cpus = [r.cpu_usage for r in rows]
        error_rates = [r.error_rate for r in rows]
        anomaly_count = sum(1 for r in rows if r.is_anomaly)

        return {
            "service": service,
            "record_count": len(rows),
            "anomaly_count": anomaly_count,
            "latency": {
                "mean": round(float(np.mean(latencies)), 2),
                "max": round(float(np.max(latencies)), 2),
                "std": round(float(np.std(latencies)), 2),
                "p95": round(float(np.percentile(latencies, 95)), 2),
            },
            "cpu": {
                "mean": round(float(np.mean(cpus)), 2),
                "max": round(float(np.max(cpus)), 2),
            },
            "error_rate": {
                "mean": round(float(np.mean(error_rates)), 4),
                "max": round(float(np.max(error_rates)), 4),
            },
        }


# ─────────────────────────── AGENT CLASS ─────────────────────────────────────

SYSTEM_PROMPT = """You are an AIOps Incident Detection Agent for an e-commerce platform.

Your job is to:
1. Query the Silver layer for anomalous metrics and error logs
2. Analyse the data to determine if real incidents are occurring
3. Avoid duplicate incidents by checking existing open incidents
4. Create confirmed incidents in the Gold layer with proper severity (P1-P4)

Severity guidelines:
- P1: Service down or >30% error rate or latency >10x normal — immediate action
- P2: Significant degradation >15% error rate or latency >5x normal
- P3: Minor degradation, isolated errors
- P4: Informational, below thresholds

Always use the tools to gather data before making decisions.
Return a JSON summary of all incidents created or skipped."""


class IncidentDetectionAgent(BaseAgent):
    def __init__(self, client: anthropic.Anthropic):
        super().__init__(
            client=client,
            model=settings.claude_model,
            tool_names=[
                "query_silver_anomalies",
                "query_error_logs",
                "get_open_incidents",
                "create_incident",
                "get_service_metric_summary",
            ],
        )

    def detect(self) -> str:
        user_prompt = (
            "Analyse all services in the last 6 hours for incidents. "
            "Check anomalies, correlate with error logs, and create confirmed incidents. "
            "Return a summary of what you found and what incidents were created."
        )
        result = self.run(SYSTEM_PROMPT, user_prompt, max_iterations=30)
        print(f"  [IncidentDetectionAgent] Done.")
        return result
