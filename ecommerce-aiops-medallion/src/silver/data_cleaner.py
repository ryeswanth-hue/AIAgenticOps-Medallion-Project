"""
Silver Layer — Data Cleaner.
Reads from Bronze tables, cleans and normalises the data,
and writes to Silver tables.
"""

import numpy as np
from datetime import datetime
from typing import List

from sqlalchemy import select
from src.database.connection import get_db
from src.database.models import (
    BronzeSystemMetric, BronzeLog, BronzeTransaction,
    SilverMetric, SilverLog, SilverTransaction,
)


class DataCleaner:
    """Cleans Bronze data and produces Silver records."""

    def run(self) -> dict:
        counts = {}
        counts["metrics"] = self._clean_metrics()
        counts["logs"] = self._clean_logs()
        counts["transactions"] = self._clean_transactions()
        return counts

    # ─────────────────────────── METRICS ─────────────────────────────────────

    def _clean_metrics(self) -> int:
        with get_db() as db:
            bronze_rows = db.execute(select(BronzeSystemMetric)).scalars().all()
            silver_rows = []

            for row in bronze_rows:
                error_rate = (
                    row.error_count / row.request_count
                    if row.request_count and row.request_count > 0 else 0.0
                )
                silver_rows.append(SilverMetric(
                    service=row.service or "unknown",
                    timestamp=row.timestamp or datetime.utcnow(),
                    cpu_usage=self._clamp(row.cpu_usage, 0, 100),
                    memory_usage=self._clamp(row.memory_usage, 0, 100),
                    request_count=max(0, row.request_count or 0),
                    error_count=max(0, row.error_count or 0),
                    avg_latency_ms=max(0, row.avg_latency_ms or 0),
                    error_rate=round(error_rate, 4),
                    # Z-scores computed later by anomaly detector
                    latency_zscore=0.0,
                    cpu_zscore=0.0,
                    error_rate_zscore=0.0,
                    is_anomaly=False,
                ))

            db.bulk_save_objects(silver_rows)
        print(f"  [Silver] Cleaned {len(silver_rows):,} metric records")
        return len(silver_rows)

    # ─────────────────────────── LOGS ────────────────────────────────────────

    def _clean_logs(self) -> int:
        with get_db() as db:
            bronze_rows = db.execute(select(BronzeLog)).scalars().all()
            silver_rows = []

            for row in bronze_rows:
                is_error = row.level in ("ERROR", "CRITICAL") or (row.status_code or 0) >= 500
                error_category = self._classify_error(row)
                silver_rows.append(SilverLog(
                    service=row.service or "unknown",
                    level=row.level or "INFO",
                    message=row.message or "",
                    endpoint=row.endpoint or "",
                    status_code=row.status_code or 0,
                    latency_ms=max(0, row.latency_ms or 0),
                    timestamp=row.timestamp or datetime.utcnow(),
                    is_error=is_error,
                    error_category=error_category,
                ))

            db.bulk_save_objects(silver_rows)
        print(f"  [Silver] Cleaned {len(silver_rows):,} log records")
        return len(silver_rows)

    # ─────────────────────────── TRANSACTIONS ────────────────────────────────

    def _clean_transactions(self) -> int:
        with get_db() as db:
            bronze_rows = db.execute(select(BronzeTransaction)).scalars().all()
            silver_rows = []

            for row in bronze_rows:
                is_failed = row.status in ("cancelled", "refunded")
                failure_reason = row.raw_payload.get("failure_reason") if row.raw_payload else None
                silver_rows.append(SilverTransaction(
                    order_id=row.order_id or "",
                    user_id=row.user_id or "",
                    product_id=row.product_id or "",
                    amount=max(0, row.amount or 0),
                    status=row.status or "unknown",
                    payment_method=row.payment_method or "unknown",
                    timestamp=row.timestamp or datetime.utcnow(),
                    is_failed=is_failed,
                    failure_reason=failure_reason,
                ))

            db.bulk_save_objects(silver_rows)
        print(f"  [Silver] Cleaned {len(silver_rows):,} transaction records")
        return len(silver_rows)

    # ─────────────────────────── HELPERS ─────────────────────────────────────

    def _clamp(self, val, lo, hi):
        if val is None:
            return lo
        return max(lo, min(hi, val))

    def _classify_error(self, row) -> str:
        code = row.status_code or 0
        latency = row.latency_ms or 0
        msg = (row.message or "").lower()

        if "timeout" in msg or latency > 5000:
            return "timeout"
        if code >= 500:
            return "5xx"
        if code >= 400:
            return "4xx"
        if "payment" in msg or "payment" in (row.service or ""):
            return "payment_failure"
        return "none"
