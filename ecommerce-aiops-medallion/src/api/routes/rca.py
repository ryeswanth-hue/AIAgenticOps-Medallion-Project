"""RCA API routes — trigger and retrieve Root Cause Analysis."""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional

from src.database.connection import get_db
from src.database.models import GoldRCA, GoldIncident
from config.settings import settings

router = APIRouter(prefix="/rca", tags=["RCA"])


class RCAOut(BaseModel):
    incident_id: str
    root_cause: Optional[str]
    contributing_factors: Optional[list]
    affected_services: Optional[list]
    confidence_score: Optional[float]
    ai_analysis: Optional[str]

    class Config:
        from_attributes = True


@router.get("/{incident_id}", response_model=RCAOut)
def get_rca(incident_id: str):
    """Get stored RCA for an incident."""
    with get_db() as db:
        row = db.execute(
            select(GoldRCA).where(GoldRCA.incident_id == incident_id)
        ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="No RCA found for this incident")
    return RCAOut.model_validate(row)


@router.post("/{incident_id}/trigger")
def trigger_rca(incident_id: str, background_tasks: BackgroundTasks):
    """Trigger RCA analysis for an incident (runs in background)."""
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY not configured")

    with get_db() as db:
        incident = db.execute(
            select(GoldIncident).where(GoldIncident.incident_id == incident_id)
        ).scalar_one_or_none()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    def _run_rca():
        import anthropic
        from src.agents.rca_agent import RCAAgent
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        agent = RCAAgent(client)
        agent.analyse(incident_id)

    background_tasks.add_task(_run_rca)
    return {"status": "triggered", "incident_id": incident_id, "message": "RCA running in background"}
