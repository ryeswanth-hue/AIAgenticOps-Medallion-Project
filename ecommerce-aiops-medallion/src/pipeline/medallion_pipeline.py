"""
Medallion Pipeline Orchestrator.
Coordinates Bronze → Silver → Gold data transformations,
then hands off to the AI agent pipeline.
"""

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from src.data_generation.ecommerce_simulator import EcommerceSimulator
from src.data_generation.incident_injector import IncidentInjector
from src.bronze.bronze_processor import BronzeProcessor
from src.silver.data_cleaner import DataCleaner
from src.silver.anomaly_detector import AnomalyDetector
from src.gold.incident_aggregator import IncidentAggregator
from src.agents.orchestrator import OrchestratorAgent
from src.database.connection import init_db
from config.settings import settings

console = Console()


class MedallionPipeline:
    """
    Full end-to-end Medallion Architecture pipeline:

    [Data Generation] → [Bronze] → [Silver] → [Gold] → [AI Agents]
    """

    def run(self, skip_generation: bool = False):
        console.print(Panel.fit(
            "[bold cyan]Ecommerce AIOps — Medallion Architecture[/bold cyan]\n"
            "[dim]Bronze → Silver → Gold → Multi-Agent AI[/dim]",
            border_style="cyan",
        ))

        # Step 0: Init database
        console.print("\n[bold]Step 0:[/bold] Initialising database...")
        init_db()
        console.print("  [green]✓[/green] Database ready")

        # Step 1: Data generation (Bronze raw files)
        if not skip_generation:
            console.print("\n[bold]Step 1:[/bold] [yellow]BRONZE — Generating e-commerce data[/yellow]")
            sim = EcommerceSimulator(settings.bronze_data_path)
            with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as p:
                t1 = p.add_task("Generating system metrics...", total=None)
                sim.generate_metrics(hours=24, interval_minutes=5)
                p.update(t1, description="[green]✓ Metrics generated[/green]")

                t2 = p.add_task("Generating transactions...", total=None)
                sim.generate_transactions(count=5000)
                p.update(t2, description="[green]✓ Transactions generated[/green]")

                t3 = p.add_task("Generating application logs...", total=None)
                sim.generate_logs(count=10000)
                p.update(t3, description="[green]✓ Logs generated[/green]")

                t4 = p.add_task("Generating user events...", total=None)
                sim.generate_events(count=20000)
                p.update(t4, description="[green]✓ Events generated[/green]")

            # Inject incidents into data
            console.print("\n[bold]Step 1b:[/bold] [red]BRONZE — Injecting incidents[/red]")
            injector = IncidentInjector(settings.bronze_data_path)
            incidents = injector.inject_all_incidents()
            console.print(f"  [green]✓[/green] Injected [bold]{len(incidents)}[/bold] incident patterns")

        # Step 2: Bronze layer ingestion
        console.print("\n[bold]Step 2:[/bold] [yellow]BRONZE — Database ingestion[/yellow]")
        bronze = BronzeProcessor()
        bronze_counts = bronze.run()
        self._print_counts("Bronze ingestion", bronze_counts)

        # Step 3: Silver layer — clean + feature engineer
        console.print("\n[bold]Step 3:[/bold] [blue]SILVER — Cleaning & normalising[/blue]")
        cleaner = DataCleaner()
        silver_counts = cleaner.run()
        self._print_counts("Silver cleaning", silver_counts)

        # Step 4: Silver layer — anomaly detection
        console.print("\n[bold]Step 4:[/bold] [blue]SILVER — Anomaly detection[/blue]")
        detector = AnomalyDetector()
        anomaly_count = detector.run()
        console.print(f"  [green]✓[/green] [bold]{anomaly_count}[/bold] anomalies flagged")

        # Step 5: Gold layer — aggregate anomalies into incidents
        console.print("\n[bold]Step 5:[/bold] [magenta]GOLD — Aggregating incidents[/magenta]")
        aggregator = IncidentAggregator()
        incident_ids = aggregator.run()
        console.print(f"  [green]✓[/green] [bold]{len(incident_ids)}[/bold] incidents created in Gold layer")

        # Step 6: AI Agent pipeline
        console.print("\n[bold]Step 6:[/bold] [red]AI AGENTS — Multi-agent AIOps pipeline[/red]")
        if not settings.anthropic_api_key:
            console.print("  [yellow]⚠ ANTHROPIC_API_KEY not set — skipping AI agent pipeline[/yellow]")
            console.print("  [dim]Set ANTHROPIC_API_KEY in .env to run the full AI pipeline[/dim]")
        else:
            orchestrator = OrchestratorAgent()
            final_result = orchestrator.run_pipeline()
            console.print("\n[bold green]Pipeline Complete![/bold green]")
            console.print(Panel(final_result[:1000] + "..." if len(final_result) > 1000 else final_result,
                                title="Orchestrator Final Report", border_style="green"))

        # Summary
        console.print("\n")
        console.print(Panel.fit(
            "[bold green]✓ Medallion Pipeline Complete[/bold green]\n"
            f"  Bronze records: {sum(bronze_counts.values()):,}\n"
            f"  Silver records: {sum(silver_counts.values()):,}\n"
            f"  Anomalies detected: {anomaly_count}\n"
            f"  Gold incidents: {len(incident_ids)}\n"
            f"  Reports: data/gold/dashboards/",
            border_style="green",
        ))

    def _print_counts(self, label: str, counts: dict):
        table = Table(show_header=True, header_style="bold dim")
        table.add_column("Layer", style="dim")
        table.add_column("Records", justify="right", style="cyan")
        for k, v in counts.items():
            table.add_row(k, f"{v:,}")
        console.print(f"  [green]✓[/green] {label}")
        console.print(table)
