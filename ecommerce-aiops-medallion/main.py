"""
Ecommerce AIOps — Medallion Architecture
Entry point with CLI commands.

Usage:
  python main.py pipeline          # Run full Bronze→Silver→Gold→AI pipeline
  python main.py api               # Start FastAPI server
  python main.py detect            # Run incident detection only
  python main.py rca INC-XXXXXXXX  # Run RCA for a specific incident
  python main.py report            # Generate report only
"""

import sys
import typer
import uvicorn
from pathlib import Path

app = typer.Typer(help="Ecommerce AIOps — Medallion Architecture CLI")


@app.command()
def pipeline(
    skip_generation: bool = typer.Option(
        False, "--skip-gen", help="Skip data generation (use existing Bronze data)"
    )
):
    """Run the full Medallion pipeline: data gen → Bronze → Silver → Gold → AI agents."""
    from src.pipeline.medallion_pipeline import MedallionPipeline
    MedallionPipeline().run(skip_generation=skip_generation)


@app.command()
def api(
    host: str = typer.Option("0.0.0.0", help="Host to bind"),
    port: int = typer.Option(8000, help="Port to bind"),
    reload: bool = typer.Option(False, help="Enable auto-reload"),
):
    """Start the FastAPI server."""
    uvicorn.run("src.api.main:app", host=host, port=port, reload=reload)


@app.command()
def detect():
    """Run the Incident Detection Agent only (requires Silver data)."""
    import anthropic
    from config.settings import settings
    from src.agents.incident_detection_agent import IncidentDetectionAgent
    from src.database.connection import init_db

    init_db()
    if not settings.anthropic_api_key:
        typer.echo("ERROR: Set ANTHROPIC_API_KEY in .env")
        raise typer.Exit(1)

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    agent = IncidentDetectionAgent(client)
    result = agent.detect()
    typer.echo(result)


@app.command()
def rca(incident_id: str = typer.Argument(..., help="Incident ID, e.g. INC-XXXXXXXX")):
    """Run Root Cause Analysis for a specific incident."""
    import anthropic
    from config.settings import settings
    from src.agents.rca_agent import RCAAgent
    from src.database.connection import init_db

    init_db()
    if not settings.anthropic_api_key:
        typer.echo("ERROR: Set ANTHROPIC_API_KEY in .env")
        raise typer.Exit(1)

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    agent = RCAAgent(client)
    result = agent.analyse(incident_id)
    typer.echo(result)


@app.command()
def report():
    """Generate the HTML report using the Report Agent."""
    import anthropic
    from config.settings import settings
    from src.agents.report_agent import ReportAgent
    from src.database.connection import init_db

    init_db()
    if not settings.anthropic_api_key:
        typer.echo("ERROR: Set ANTHROPIC_API_KEY in .env")
        raise typer.Exit(1)

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    agent = ReportAgent(client)
    result = agent.generate()
    typer.echo(result)
    typer.echo("\nReport saved to: data/gold/dashboards/")


@app.command()
def seed_only():
    """Run only data generation + bronze ingestion (no AI)."""
    from src.database.connection import init_db
    from src.data_generation.ecommerce_simulator import EcommerceSimulator
    from src.data_generation.incident_injector import IncidentInjector
    from src.bronze.bronze_processor import BronzeProcessor
    from src.silver.data_cleaner import DataCleaner
    from src.silver.anomaly_detector import AnomalyDetector
    from src.gold.incident_aggregator import IncidentAggregator
    from config.settings import settings

    init_db()
    sim = EcommerceSimulator(settings.bronze_data_path)
    sim.generate_metrics()
    sim.generate_transactions()
    sim.generate_logs()
    sim.generate_events()

    IncidentInjector(settings.bronze_data_path).inject_all_incidents()
    BronzeProcessor().run()
    DataCleaner().run()
    AnomalyDetector().run()
    IncidentAggregator().run()
    typer.echo("Data generation and Bronze→Silver→Gold complete. API can now be started.")


if __name__ == "__main__":
    app()
