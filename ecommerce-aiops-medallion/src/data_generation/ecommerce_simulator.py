"""
E-commerce data simulator.
Generates realistic synthetic data for: metrics, logs, transactions, events.
"""

import json
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any

from faker import Faker

fake = Faker()

SERVICES = ["api-gateway", "order-service", "payment-service", "inventory-service",
            "user-service", "notification-service", "search-service"]
PRODUCTS = [f"PROD-{i:04d}" for i in range(1, 201)]
PAYMENT_METHODS = ["credit_card", "debit_card", "paypal", "apple_pay", "google_pay"]
ENDPOINTS = [
    "/api/v1/orders", "/api/v1/products", "/api/v1/cart", "/api/v1/checkout",
    "/api/v1/payments", "/api/v1/users", "/api/v1/search", "/api/v1/inventory"
]
ORDER_STATUSES = ["pending", "confirmed", "shipped", "delivered", "cancelled", "refunded"]


class EcommerceSimulator:
    """Generates synthetic e-commerce operational data."""

    def __init__(self, bronze_path: str):
        self.bronze_path = Path(bronze_path)

    # ──────────────────────────── METRICS ────────────────────────────────────

    def generate_metrics(self, hours: int = 24, interval_minutes: int = 5) -> List[Dict]:
        """Generates system metrics time series for all services."""
        records = []
        now = datetime.utcnow()
        steps = (hours * 60) // interval_minutes

        for service in SERVICES:
            base_cpu = random.uniform(20, 50)
            base_mem = random.uniform(40, 70)
            base_latency = random.uniform(50, 200)
            base_rps = random.randint(50, 500)

            for step in range(steps):
                ts = now - timedelta(minutes=step * interval_minutes)
                cpu = max(0, min(100, base_cpu + random.gauss(0, 5)))
                mem = max(0, min(100, base_mem + random.gauss(0, 3)))
                rps = max(0, base_rps + random.randint(-30, 30))
                latency = max(1, base_latency + random.gauss(0, 20))
                err_count = max(0, int(rps * random.uniform(0, 0.02)))

                record = {
                    "id": str(uuid.uuid4()),
                    "service": service,
                    "timestamp": ts.isoformat(),
                    "cpu_usage": round(cpu, 2),
                    "memory_usage": round(mem, 2),
                    "request_count": rps,
                    "error_count": err_count,
                    "avg_latency_ms": round(latency, 2),
                }
                records.append(record)

        self._save_json(records, "metrics", "system_metrics.json")
        return records

    # ──────────────────────────── TRANSACTIONS ───────────────────────────────

    def generate_transactions(self, count: int = 5000) -> List[Dict]:
        """Generates synthetic e-commerce transactions."""
        records = []
        now = datetime.utcnow()

        for _ in range(count):
            ts = now - timedelta(minutes=random.randint(0, 1440))
            status = random.choices(
                ORDER_STATUSES, weights=[10, 40, 20, 20, 5, 5]
            )[0]
            record = {
                "order_id": f"ORD-{uuid.uuid4().hex[:8].upper()}",
                "user_id": f"USR-{random.randint(1000, 9999)}",
                "product_id": random.choice(PRODUCTS),
                "amount": round(random.uniform(9.99, 999.99), 2),
                "status": status,
                "payment_method": random.choice(PAYMENT_METHODS),
                "timestamp": ts.isoformat(),
            }
            records.append(record)

        self._save_json(records, "transactions", "transactions.json")
        return records

    # ──────────────────────────── LOGS ───────────────────────────────────────

    def generate_logs(self, count: int = 10000) -> List[Dict]:
        """Generates structured application logs."""
        records = []
        now = datetime.utcnow()
        log_levels = ["INFO", "INFO", "INFO", "WARN", "ERROR"]

        for _ in range(count):
            ts = now - timedelta(seconds=random.randint(0, 86400))
            service = random.choice(SERVICES)
            level = random.choices(log_levels, weights=[60, 60, 60, 15, 5])[0]
            endpoint = random.choice(ENDPOINTS)
            status_code = (
                random.choice([200, 200, 200, 201, 204])
                if level == "INFO"
                else random.choice([400, 404, 422, 500, 502, 503])
                if level == "ERROR"
                else random.choice([301, 400, 429])
            )
            latency = (
                random.gauss(80, 30) if level == "INFO"
                else random.gauss(2000, 500) if level == "ERROR"
                else random.gauss(300, 100)
            )
            messages_map = {
                "INFO": f"Request to {endpoint} completed successfully",
                "WARN": f"Slow response detected on {endpoint} — {abs(latency):.0f}ms",
                "ERROR": f"Unhandled exception in {service} on {endpoint}: {fake.sentence()}",
            }
            record = {
                "log_id": str(uuid.uuid4()),
                "service": service,
                "level": level,
                "message": messages_map[level],
                "endpoint": endpoint,
                "status_code": status_code,
                "latency_ms": round(abs(latency), 2),
                "timestamp": ts.isoformat(),
            }
            records.append(record)

        self._save_json(records, "logs", "app_logs.json")
        return records

    # ──────────────────────────── EVENTS ─────────────────────────────────────

    def generate_events(self, count: int = 20000) -> List[Dict]:
        """Generates user behaviour events."""
        records = []
        now = datetime.utcnow()
        pages = ["/home", "/product", "/cart", "/checkout", "/account", "/search"]
        actions = ["view", "click", "add_to_cart", "remove_from_cart", "purchase", "search"]

        for _ in range(count):
            ts = now - timedelta(seconds=random.randint(0, 86400))
            record = {
                "event_id": str(uuid.uuid4()),
                "event_type": "user_interaction",
                "user_id": f"USR-{random.randint(1000, 9999)}",
                "session_id": f"SES-{uuid.uuid4().hex[:12]}",
                "page": random.choice(pages),
                "action": random.choice(actions),
                "timestamp": ts.isoformat(),
            }
            records.append(record)

        self._save_json(records, "events", "user_events.json")
        return records

    # ──────────────────────────── HELPERS ────────────────────────────────────

    def _save_json(self, records: List[Dict], subfolder: str, filename: str):
        path = self.bronze_path / subfolder / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(records, f, indent=2, default=str)
        print(f"  [Simulator] Saved {len(records):,} records → {path}")
