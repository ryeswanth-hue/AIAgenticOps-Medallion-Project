"""Report generation API routes."""

from pathlib import Path
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy import select

from src.database.connection import get_db
from src.database.models import GoldReport
from config.settings import settings

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/")
def list_reports():
    """List all generated reports."""
    with get_db() as db:
        rows = db.execute(
            select(GoldReport).order_by(GoldReport.created_at.desc())
        ).scalars().all()
        return [
            {
                "id": r.id,
                "created_at": r.created_at.isoformat(),
                "incident_id": r.incident_id,
                "report_path": r.report_path,
                "total_incidents": r.total_incidents,
                "p1_count": r.p1_count,
                "p2_count": r.p2_count,
                "summary": r.summary,
            }
            for r in rows
        ]


@router.get("/latest")
def get_latest_report():
    """Download the latest HTML report."""
    dashboard_path = Path(settings.gold_data_path) / "dashboards"
    files = sorted(dashboard_path.glob("report_*.html"), reverse=True)
    if not files:
        raise HTTPException(status_code=404, detail="No reports found. Run the pipeline first.")
    return FileResponse(str(files[0]), media_type="text/html", filename=files[0].name)


@router.post("/generate")
def trigger_report(background_tasks: BackgroundTasks):
    """Trigger report generation (runs in background)."""
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY not configured")

    def _run():
        import anthropic
        from src.agents.report_agent import ReportAgent
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        agent = ReportAgent(client)
        agent.generate()

    background_tasks.add_task(_run)
    return {"status": "triggered", "message": "Report generation running in background"}
