"""Metrics query API routes (Silver layer)."""

from typing import List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Query
from sqlalchemy import select
from pydantic import BaseModel

from src.database.connection import get_db
from src.database.models import SilverMetric

router = APIRouter(prefix="/metrics", tags=["Metrics"])


class MetricOut(BaseModel):
    service: str
    timestamp: Optional[datetime]
    avg_latency_ms: float
    cpu_usage: float
    error_rate: float
    request_count: int
    is_anomaly: bool
    anomaly_type: Optional[str]

    class Config:
        from_attributes = True


@router.get("/", response_model=List[MetricOut])
def get_metrics(
    service: Optional[str] = Query(None, description="Filter by service name"),
    anomalies_only: bool = Query(False),
    hours: int = Query(6, description="Look-back hours"),
    limit: int = Query(500),
):
    """Query Silver-layer metric records."""
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    with get_db() as db:
        q = select(SilverMetric).where(SilverMetric.timestamp >= cutoff)
        if service:
            q = q.where(SilverMetric.service == service)
        if anomalies_only:
            q = q.where(SilverMetric.is_anomaly == True)
        rows = db.execute(q.order_by(SilverMetric.timestamp.desc()).limit(limit)).scalars().all()
        return [MetricOut.model_validate(r) for r in rows]


@router.get("/services")
def list_services():
    """List all unique service names in the metrics table."""
    with get_db() as db:
        rows = db.execute(select(SilverMetric.service).distinct()).all()
    return {"services": [r[0] for r in rows]}


@router.get("/anomaly-summary")
def anomaly_summary(hours: int = Query(24)):
    """Returns anomaly counts per service per type."""
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    with get_db() as db:
        rows = db.execute(
            select(SilverMetric).where(
                SilverMetric.is_anomaly == True,
                SilverMetric.timestamp >= cutoff,
            )
        ).scalars().all()

    summary: dict = {}
    for r in rows:
        key = (r.service, r.anomaly_type or "unknown")
        summary[key] = summary.get(key, 0) + 1

    return [
        {"service": svc, "anomaly_type": atype, "count": cnt}
        for (svc, atype), cnt in sorted(summary.items(), key=lambda x: -x[1])
    ]
