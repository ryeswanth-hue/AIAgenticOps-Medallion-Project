"""Incident management API routes."""

from typing import List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, update

from src.database.connection import get_db
from src.database.models import GoldIncident, GoldRCA, GoldRemediation
from pydantic import BaseModel

router = APIRouter(prefix="/incidents", tags=["Incidents"])


class IncidentOut(BaseModel):
    incident_id: str
    title: str
    severity: str
    status: str
    service: str
    incident_type: str
    detected_at: Optional[datetime]
    resolved_at: Optional[datetime]
    anomaly_details: Optional[dict]
    ai_classification: Optional[str]

    class Config:
        from_attributes = True


class IncidentUpdate(BaseModel):
    status: Optional[str] = None
    resolved_at: Optional[datetime] = None


@router.get("/", response_model=List[IncidentOut])
def list_incidents(
    severity: Optional[str] = Query(None, description="P1 / P2 / P3 / P4"),
    status: Optional[str] = Query(None, description="open / investigating / resolved"),
    hours: int = Query(24, description="Look-back window in hours"),
    service: Optional[str] = Query(None),
):
    """List all Gold-layer incidents."""
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    with get_db() as db:
        q = select(GoldIncident).where(GoldIncident.detected_at >= cutoff)
        if severity:
            q = q.where(GoldIncident.severity == severity)
        if status:
            q = q.where(GoldIncident.status == status)
        if service:
            q = q.where(GoldIncident.service == service)
        rows = db.execute(q.order_by(GoldIncident.detected_at.desc())).scalars().all()
        return [IncidentOut.model_validate(r) for r in rows]


@router.get("/{incident_id}", response_model=IncidentOut)
def get_incident(incident_id: str):
    """Get a single incident by ID."""
    with get_db() as db:
        row = db.execute(
            select(GoldIncident).where(GoldIncident.incident_id == incident_id)
        ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Incident not found")
    return IncidentOut.model_validate(row)


@router.patch("/{incident_id}")
def update_incident(incident_id: str, payload: IncidentUpdate):
    """Update incident status or resolved_at."""
    with get_db() as db:
        row = db.execute(
            select(GoldIncident).where(GoldIncident.incident_id == incident_id)
        ).scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Incident not found")
        if payload.status:
            row.status = payload.status
        if payload.resolved_at:
            row.resolved_at = payload.resolved_at
    return {"status": "updated", "incident_id": incident_id}


@router.get("/{incident_id}/full")
def get_incident_full(incident_id: str):
    """Get incident with associated RCA and remediation."""
    with get_db() as db:
        incident = db.execute(
            select(GoldIncident).where(GoldIncident.incident_id == incident_id)
        ).scalar_one_or_none()
        rca = db.execute(
            select(GoldRCA).where(GoldRCA.incident_id == incident_id)
        ).scalar_one_or_none()
        remediation = db.execute(
            select(GoldRemediation).where(GoldRemediation.incident_id == incident_id)
        ).scalar_one_or_none()

    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    return {
        "incident": IncidentOut.model_validate(incident),
        "rca": {
            "root_cause": rca.root_cause,
            "contributing_factors": rca.contributing_factors,
            "confidence_score": rca.confidence_score,
            "ai_analysis": rca.ai_analysis,
        } if rca else None,
        "remediation": {
            "immediate_actions": remediation.immediate_actions,
            "long_term_fixes": remediation.long_term_fixes,
            "estimated_resolution_time": remediation.estimated_resolution_time,
        } if remediation else None,
    }
