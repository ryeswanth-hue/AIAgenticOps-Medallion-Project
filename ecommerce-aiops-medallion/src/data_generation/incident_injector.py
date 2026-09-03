"""
Incident Injector — injects realistic anomalies into the generated data.

Incident types:
  - latency_spike     : sudden latency increase in one service
  - error_surge       : rapid increase in error rate
  - payment_failure   : payment-service failures cascade
  - memory_leak       : steadily rising memory usage
  - traffic_spike     : sudden traffic burst overwhelming a service
"""

import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict


class IncidentInjector:
    """Injects incident patterns into bronze-layer metrics and logs."""

    def __init__(self, bronze_path: str):
        self.bronze_path = Path(bronze_path)

    def inject_all_incidents(self) -> List[Dict]:
        """Injects a set of realistic incidents and returns a manifest."""
        incidents = []
        incidents.append(self._inject_latency_spike("payment-service"))
        incidents.append(self._inject_error_surge("order-service"))
        incidents.append(self._inject_payment_cascade())
        incidents.append(self._inject_memory_leak("api-gateway"))
        incidents.append(self._inject_traffic_spike("search-service"))
        self._save_manifest(incidents)
        return incidents

    # ──────────────────────── INJECTION METHODS ──────────────────────────────

    def _inject_latency_spike(self, service: str) -> Dict:
        metrics = self._load_json("metrics", "system_metrics.json")
        spike_start = datetime.utcnow() - timedelta(hours=2)
        spike_end = spike_start + timedelta(minutes=45)

        injected = 0
        for m in metrics:
            if m["service"] == service:
                ts = datetime.fromisoformat(m["timestamp"])
                if spike_start <= ts <= spike_end:
                    m["avg_latency_ms"] = round(m["avg_latency_ms"] * random.uniform(8, 15), 2)
                    m["error_count"] = int(m["error_count"] * random.uniform(3, 6))
                    injected += 1

        self._save_json(metrics, "metrics", "system_metrics.json")
        print(f"  [Injector] Latency spike injected into {service} ({injected} records)")
        return {
            "type": "latency_spike",
            "service": service,
            "start": spike_start.isoformat(),
            "end": spike_end.isoformat(),
            "severity": "P1",
        }

    def _inject_error_surge(self, service: str) -> Dict:
        metrics = self._load_json("metrics", "system_metrics.json")
        surge_start = datetime.utcnow() - timedelta(hours=3, minutes=30)
        surge_end = surge_start + timedelta(minutes=30)

        injected = 0
        for m in metrics:
            if m["service"] == service:
                ts = datetime.fromisoformat(m["timestamp"])
                if surge_start <= ts <= surge_end:
                    m["error_count"] = int(m["request_count"] * random.uniform(0.3, 0.6))
                    m["cpu_usage"] = min(100, m["cpu_usage"] * random.uniform(1.5, 2.0))
                    injected += 1

        self._save_json(metrics, "metrics", "system_metrics.json")

        # Also inject error logs
        logs = self._load_json("logs", "app_logs.json")
        for _ in range(500):
            ts = surge_start + timedelta(seconds=random.randint(0, 1800))
            logs.append({
                "log_id": f"inj-{random.randint(100000,999999)}",
                "service": service,
                "level": "ERROR",
                "message": f"NullPointerException in OrderProcessor: database connection refused",
                "endpoint": "/api/v1/orders",
                "status_code": 500,
                "latency_ms": round(random.uniform(5000, 30000), 2),
                "timestamp": ts.isoformat(),
            })
        self._save_json(logs, "logs", "app_logs.json")
        print(f"  [Injector] Error surge injected into {service} ({injected} records)")
        return {
            "type": "error_surge",
            "service": service,
            "start": surge_start.isoformat(),
            "end": surge_end.isoformat(),
            "severity": "P1",
        }

    def _inject_payment_cascade(self) -> Dict:
        txns = self._load_json("transactions", "transactions.json")
        fail_start = datetime.utcnow() - timedelta(hours=1)
        fail_end = fail_start + timedelta(minutes=60)

        injected = 0
        for t in txns:
            ts = datetime.fromisoformat(t["timestamp"])
            if fail_start <= ts <= fail_end and t["payment_method"] == "credit_card":
                t["status"] = "cancelled"
                t["failure_reason"] = "payment_gateway_timeout"
                injected += 1

        self._save_json(txns, "transactions", "transactions.json")
        print(f"  [Injector] Payment cascade injected ({injected} failed transactions)")
        return {
            "type": "payment_failure",
            "service": "payment-service",
            "start": fail_start.isoformat(),
            "end": fail_end.isoformat(),
            "severity": "P2",
        }

    def _inject_memory_leak(self, service: str) -> Dict:
        metrics = self._load_json("metrics", "system_metrics.json")
        leak_start = datetime.utcnow() - timedelta(hours=6)
        step = 0

        injected = 0
        for m in sorted(metrics, key=lambda x: x["timestamp"]):
            if m["service"] == service:
                ts = datetime.fromisoformat(m["timestamp"])
                if ts >= leak_start:
                    m["memory_usage"] = min(99, m["memory_usage"] + step * 0.5)
                    step += 1
                    injected += 1

        self._save_json(metrics, "metrics", "system_metrics.json")
        print(f"  [Injector] Memory leak injected into {service} ({injected} records)")
        return {
            "type": "memory_leak",
            "service": service,
            "start": leak_start.isoformat(),
            "end": datetime.utcnow().isoformat(),
            "severity": "P2",
        }

    def _inject_traffic_spike(self, service: str) -> Dict:
        metrics = self._load_json("metrics", "system_metrics.json")
        spike_start = datetime.utcnow() - timedelta(hours=4)
        spike_end = spike_start + timedelta(minutes=20)

        injected = 0
        for m in metrics:
            if m["service"] == service:
                ts = datetime.fromisoformat(m["timestamp"])
                if spike_start <= ts <= spike_end:
                    m["request_count"] = int(m["request_count"] * random.uniform(10, 20))
                    m["cpu_usage"] = min(100, m["cpu_usage"] * random.uniform(2, 3))
                    m["avg_latency_ms"] = m["avg_latency_ms"] * random.uniform(3, 7)
                    injected += 1

        self._save_json(metrics, "metrics", "system_metrics.json")
        print(f"  [Injector] Traffic spike injected into {service} ({injected} records)")
        return {
            "type": "traffic_spike",
            "service": service,
            "start": spike_start.isoformat(),
            "end": spike_end.isoformat(),
            "severity": "P3",
        }

    # ──────────────────────── HELPERS ────────────────────────────────────────

    def _load_json(self, subfolder: str, filename: str) -> List[Dict]:
        path = self.bronze_path / subfolder / filename
        if not path.exists():
            return []
        with open(path) as f:
            return json.load(f)

    def _save_json(self, records: List[Dict], subfolder: str, filename: str):
        path = self.bronze_path / subfolder / filename
        with open(path, "w") as f:
            json.dump(records, f, indent=2, default=str)

    def _save_manifest(self, incidents: List[Dict]):
        path = self.bronze_path / "incident_manifest.json"
        with open(path, "w") as f:
            json.dump(incidents, f, indent=2)
        print(f"  [Injector] Manifest saved → {path}")
