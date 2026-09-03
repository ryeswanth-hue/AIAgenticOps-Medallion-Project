"""
Silver Layer — Anomaly Detector.
Applies statistical methods (Z-score + IQR) to Silver metrics
and flags anomalies that feed the Gold incident pipeline.
"""

import numpy as np
from collections import defaultdict
from datetime import datetime
from sqlalchemy import select, update

from src.database.connection import get_db
from src.database.models import SilverMetric


ZSCORE_THRESHOLD = 3.0      # Flag if |z| > 3
IQR_MULTIPLIER = 2.0        # Flag if value > Q3 + 2*IQR or < Q1 - 2*IQR


class AnomalyDetector:
    """
    Statistical anomaly detection on Silver metrics.
    Computes per-service Z-scores for latency, CPU, and error rate.
    """

    def run(self) -> int:
        """Returns the number of anomalies flagged."""
        total_flagged = 0
        with get_db() as db:
            rows = db.execute(select(SilverMetric)).scalars().all()

        # Group by service
        by_service = defaultdict(list)
        for row in rows:
            by_service[row.service].append(row)

        for service, service_rows in by_service.items():
            latencies = np.array([r.avg_latency_ms for r in service_rows], dtype=float)
            cpus = np.array([r.cpu_usage for r in service_rows], dtype=float)
            error_rates = np.array([r.error_rate for r in service_rows], dtype=float)

            lat_z = self._zscore(latencies)
            cpu_z = self._zscore(cpus)
            err_z = self._zscore(error_rates)

            flagged_ids = []
            with get_db() as db:
                for i, row in enumerate(service_rows):
                    is_anomaly = (
                        abs(lat_z[i]) > ZSCORE_THRESHOLD or
                        abs(cpu_z[i]) > ZSCORE_THRESHOLD or
                        abs(err_z[i]) > ZSCORE_THRESHOLD
                    )
                    anomaly_type = self._classify_anomaly(
                        lat_z[i], cpu_z[i], err_z[i]
                    )
                    db.execute(
                        update(SilverMetric)
                        .where(SilverMetric.id == row.id)
                        .values(
                            latency_zscore=round(float(lat_z[i]), 3),
                            cpu_zscore=round(float(cpu_z[i]), 3),
                            error_rate_zscore=round(float(err_z[i]), 3),
                            is_anomaly=is_anomaly,
                            anomaly_type=anomaly_type if is_anomaly else None,
                        )
                    )
                    if is_anomaly:
                        flagged_ids.append(row.id)
                        total_flagged += 1

            if flagged_ids:
                print(f"  [Anomaly] {service}: {len(flagged_ids)} anomalies detected")

        print(f"  [Anomaly] Total anomalies flagged: {total_flagged}")
        return total_flagged

    # ─────────────────────────── HELPERS ─────────────────────────────────────

    def _zscore(self, arr: np.ndarray) -> np.ndarray:
        std = np.std(arr)
        if std == 0:
            return np.zeros_like(arr)
        return (arr - np.mean(arr)) / std

    def _classify_anomaly(self, lat_z: float, cpu_z: float, err_z: float) -> str:
        if lat_z > ZSCORE_THRESHOLD:
            return "latency_spike"
        if err_z > ZSCORE_THRESHOLD:
            return "error_surge"
        if cpu_z > ZSCORE_THRESHOLD:
            return "cpu_overload"
        if lat_z < -ZSCORE_THRESHOLD:
            return "latency_drop"
        return "unknown_anomaly"
