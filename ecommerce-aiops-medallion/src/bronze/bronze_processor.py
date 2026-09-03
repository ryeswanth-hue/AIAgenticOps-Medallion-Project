"""
Bronze Layer Processor.
Reads raw JSON files and persists them into bronze SQLite tables.
Minimal transformation — schema validation and type coercion only.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict

from src.database.connection import get_db
from src.database.models import BronzeSystemMetric, BronzeTransaction, BronzeLog, BronzeEvent
from config.settings import settings


class BronzeProcessor:
    """Ingests raw JSON files into the Bronze layer database tables."""

    def __init__(self):
        self.bronze_path = Path(settings.bronze_data_path)

    def run(self) -> Dict[str, int]:
        """Runs full bronze ingestion. Returns count of records ingested per table."""
        counts = {}
        counts["metrics"] = self._ingest_metrics()
        counts["transactions"] = self._ingest_transactions()
        counts["logs"] = self._ingest_logs()
        counts["events"] = self._ingest_events()
        return counts

    # ──────────────────────── INGESTION METHODS ──────────────────────────────

    def _ingest_metrics(self) -> int:
        path = self.bronze_path / "metrics" / "system_metrics.json"
        if not path.exists():
            return 0
        records = self._load_json(path)
        rows = []
        for r in records:
            rows.append(BronzeSystemMetric(
                service=r.get("service"),
                timestamp=self._parse_dt(r.get("timestamp")),
                cpu_usage=float(r.get("cpu_usage", 0)),
                memory_usage=float(r.get("memory_usage", 0)),
                request_count=int(r.get("request_count", 0)),
                error_count=int(r.get("error_count", 0)),
                avg_latency_ms=float(r.get("avg_latency_ms", 0)),
                raw_payload=r,
            ))
        with get_db() as db:
            db.bulk_save_objects(rows)
        print(f"  [Bronze] Ingested {len(rows):,} metric records")
        return len(rows)

    def _ingest_transactions(self) -> int:
        path = self.bronze_path / "transactions" / "transactions.json"
        if not path.exists():
            return 0
        records = self._load_json(path)
        rows = []
        for r in records:
            rows.append(BronzeTransaction(
                order_id=r.get("order_id"),
                user_id=r.get("user_id"),
                product_id=r.get("product_id"),
                amount=float(r.get("amount", 0)),
                status=r.get("status"),
                payment_method=r.get("payment_method"),
                timestamp=self._parse_dt(r.get("timestamp")),
                raw_payload=r,
            ))
        with get_db() as db:
            db.bulk_save_objects(rows)
        print(f"  [Bronze] Ingested {len(rows):,} transaction records")
        return len(rows)

    def _ingest_logs(self) -> int:
        path = self.bronze_path / "logs" / "app_logs.json"
        if not path.exists():
            return 0
        records = self._load_json(path)
        rows = []
        for r in records:
            rows.append(BronzeLog(
                service=r.get("service"),
                level=r.get("level"),
                message=r.get("message"),
                endpoint=r.get("endpoint"),
                status_code=int(r.get("status_code", 0)),
                latency_ms=float(r.get("latency_ms", 0)),
                timestamp=self._parse_dt(r.get("timestamp")),
                raw_payload=r,
            ))
        with get_db() as db:
            db.bulk_save_objects(rows)
        print(f"  [Bronze] Ingested {len(rows):,} log records")
        return len(rows)

    def _ingest_events(self) -> int:
        path = self.bronze_path / "events" / "user_events.json"
        if not path.exists():
            return 0
        records = self._load_json(path)
        rows = []
        for r in records:
            rows.append(BronzeEvent(
                event_type=r.get("event_type"),
                user_id=r.get("user_id"),
                session_id=r.get("session_id"),
                page=r.get("page"),
                action=r.get("action"),
                timestamp=self._parse_dt(r.get("timestamp")),
                raw_payload=r,
            ))
        with get_db() as db:
            db.bulk_save_objects(rows)
        print(f"  [Bronze] Ingested {len(rows):,} event records")
        return len(rows)

    # ──────────────────────── HELPERS ────────────────────────────────────────

    def _load_json(self, path: Path) -> List[Dict]:
        with open(path) as f:
            return json.load(f)

    def _parse_dt(self, value) -> datetime:
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except Exception:
            return datetime.utcnow()
