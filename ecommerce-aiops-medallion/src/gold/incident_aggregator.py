"""
Gold Layer — Incident Aggregator.
Groups consecutive anomaly windows per service into discrete incidents
and persists them to the gold_incidents table.
"""

import uuid
from datetime import datetime, timedelta
from collections import defaultdict
from typing import List, Dict

from sqlalchemy import select

from src.database.connection import get_db
from src.database.models import SilverMetric, GoldIncident


INCIDENT_MERGE_GAP_MINUTES = 15   # Merge anomalies within 15 min into one incident
MIN_ANOMALY_WINDOW_SECONDS = 120  # Ignore blips shorter than 2 minutes


SEVERITY_MAP = {
    "latency_spike": "P1",
    "error_surge": "P1",
    "cpu_overload": "P2",
    "payment_failure": "P2",
    "latency_drop": "P3",
    "unknown_anomaly": "P3",
}


class IncidentAggregator:
    """Aggregates Silver anomalies into Gold-layer incident records."""

    def run(self) -> List[str]:
        """Returns list of created incident IDs."""
        with get_db() as db:
            anomaly_rows = (
                db.execute(
                    select(SilverMetric)
                    .where(SilverMetric.is_anomaly == True)
                    .order_by(SilverMetric.service, SilverMetric.timestamp)
                )
                .scalars()
                .all()
            )

        if not anomaly_rows:
            print("  [Gold] No anomalies found — no incidents created")
            return []

        by_service: Dict[str, List[SilverMetric]] = defaultdict(list)
        for row in anomaly_rows:
            by_service[row.service].append(row)

        created_ids = []
        for service, rows in by_service.items():
            windows = self._merge_windows(rows)
            for window in windows:
                incident_id = self._create_incident(service, window)
                if incident_id:
                    created_ids.append(incident_id)

        print(f"  [Gold] Created {len(created_ids)} incidents")
        return created_ids

    # ─────────────────────────── HELPERS ─────────────────────────────────────

    def _merge_windows(self, rows: List[SilverMetric]) -> List[List[SilverMetric]]:
        """Merge consecutive anomaly records into windows."""
        windows: List[List[SilverMetric]] = []
        current = [rows[0]]

        for row in rows[1:]:
            gap = (row.timestamp - current[-1].timestamp).total_seconds()
            if gap <= INCIDENT_MERGE_GAP_MINUTES * 60:
                current.append(row)
            else:
                windows.append(current)
                current = [row]
        windows.append(current)
        return windows

    def _create_incident(self, service: str, window: List[SilverMetric]) -> str | None:
        start = min(r.timestamp for r in window)
        end = max(r.timestamp for r in window)
        duration = (end - start).total_seconds()

        if duration < MIN_ANOMALY_WINDOW_SECONDS:
            return None

        anomaly_type = self._dominant_type(window)
        severity = SEVERITY_MAP.get(anomaly_type, "P3")
        incident_id = f"INC-{uuid.uuid4().hex[:8].upper()}"

        avg_latency = sum(r.avg_latency_ms for r in window) / len(window)
        max_cpu = max(r.cpu_usage for r in window)
        max_error_rate = max(r.error_rate for r in window)

        incident = GoldIncident(
            incident_id=incident_id,
            title=f"{anomaly_type.replace('_', ' ').title()} detected in {service}",
            severity=severity,
            status="open",
            service=service,
            incident_type=anomaly_type,
            detected_at=start,
            anomaly_details={
                "duration_seconds": duration,
                "affected_records": len(window),
                "avg_latency_ms": round(avg_latency, 2),
                "max_cpu_usage": round(max_cpu, 2),
                "max_error_rate": round(max_error_rate, 4),
                "anomaly_window_start": start.isoformat(),
                "anomaly_window_end": end.isoformat(),
            },
        )

        with get_db() as db:
            db.add(incident)

        return incident_id

    def _dominant_type(self, window: List[SilverMetric]) -> str:
        from collections import Counter
        types = [r.anomaly_type for r in window if r.anomaly_type]
        if not types:
            return "unknown_anomaly"
        return Counter(types).most_common(1)[0][0]
