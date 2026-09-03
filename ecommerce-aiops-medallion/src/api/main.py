"""FastAPI application — Ecommerce AIOps Medallion Platform."""

from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.routes.incidents import router as incidents_router
from src.api.routes.metrics import router as metrics_router
from src.api.routes.rca import router as rca_router
from src.api.routes.reports import router as reports_router
from src.database.connection import init_db

app = FastAPI(
    title="Ecommerce AIOps — Medallion Architecture",
    description=(
        "Multi-Agent AIOps platform for incident detection, RCA, and remediation. "
        "Powered by Claude Opus 5 with @tool-decorated agent functions. "
        "Data flows through Bronze → Silver → Gold Medallion layers."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(incidents_router, prefix="/api/v1")
app.include_router(metrics_router, prefix="/api/v1")
app.include_router(rca_router, prefix="/api/v1")
app.include_router(reports_router, prefix="/api/v1")


@app.on_event("startup")
async def startup():
    from pathlib import Path
    from config.settings import settings
    # Ensure data directories exist before DB init
    for path in [settings.bronze_data_path, settings.silver_data_path,
                 settings.gold_data_path,
                 str(Path(settings.gold_data_path) / "dashboards")]:
        Path(path).mkdir(parents=True, exist_ok=True)
    init_db()


@app.get("/", tags=["Health"])
def root():
    return {
        "service": "Ecommerce AIOps — Medallion Architecture",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": {
            "incidents": "/api/v1/incidents",
            "metrics": "/api/v1/metrics",
            "rca": "/api/v1/rca/{incident_id}",
            "reports": "/api/v1/reports",
        },
    }


@app.get("/health", tags=["Health"])
def health():
    return {"status": "healthy"}


@app.post("/api/v1/pipeline/run", tags=["Pipeline"])
def run_full_pipeline(background_tasks: BackgroundTasks):
    """Trigger the full Medallion + AI agent pipeline (runs in background)."""
    def _run():
        from src.pipeline.medallion_pipeline import MedallionPipeline
        MedallionPipeline().run()

    background_tasks.add_task(_run)
    return {"status": "triggered", "message": "Full pipeline running in background"}
