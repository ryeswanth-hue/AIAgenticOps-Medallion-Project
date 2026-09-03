"""
Report Agent.

Uses Claude Opus 5 with tool-calling to:
  1. Aggregate all incident data from the Gold layer
  2. Compile RCA and remediation summaries
  3. Query KPI metrics for the dashboard
  4. Generate a full HTML incident report

All tool functions are marked with @tool.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any

import anthropic
from sqlalchemy import select, func

from src.agents.base_agent import tool, BaseAgent
from src.database.connection import get_db
from src.database.models import (
    GoldIncident, GoldRCA, GoldRemediation, GoldReport,
    SilverMetric, SilverTransaction,
)
from config.settings import settings


# ─────────────────────────── TOOL FUNCTIONS ──────────────────────────────────

@tool(
    description="Get all incidents from the Gold layer with optional severity filter.",
    schema={
        "type": "object",
        "properties": {
            "severity": {"type": "string", "description": "P1 / P2 / P3 / P4 / all"},
            "status": {"type": "string", "description": "open / investigating / resolved / all"},
            "hours": {"type": "integer", "description": "Look-back hours (default 24)"},
        },
        "required": [],
    },
)
def get_all_incidents(severity: str = "all", status: str = "all", hours: int = 24) -> List[Dict]:
    """Returns incident records from the Gold layer."""
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    with get_db() as db:
        q = select(GoldIncident).where(GoldIncident.detected_at >= cutoff)
        if severity != "all":
            q = q.where(GoldIncident.severity == severity)
        if status != "all":
            q = q.where(GoldIncident.status == status)
        rows = db.execute(q.order_by(GoldIncident.detected_at.desc())).scalars().all()
        return [
            {
                "incident_id": r.incident_id,
                "title": r.title,
                "severity": r.severity,
                "status": r.status,
                "service": r.service,
                "incident_type": r.incident_type,
                "detected_at": r.detected_at.isoformat() if r.detected_at else None,
                "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
                "anomaly_details": r.anomaly_details,
            }
            for r in rows
        ]


@tool(
    description="Get the RCA and remediation summary for a specific incident.",
    schema={
        "type": "object",
        "properties": {
            "incident_id": {"type": "string", "description": "Incident ID"},
        },
        "required": ["incident_id"],
    },
)
def get_incident_full_summary(incident_id: str) -> Dict:
    """Returns combined incident + RCA + remediation data."""
    with get_db() as db:
        incident = db.execute(
            select(GoldIncident).where(GoldIncident.incident_id == incident_id)
        ).scalar_one_or_none()
        rca = db.execute(
            select(GoldRCA).where(GoldRCA.incident_id == incident_id)
        ).scalar_one_or_none()
        remediation = db.execute(
            select(GoldRemediation).where(GoldRemediation.incident_id == incident_id)
        ).scalar_one_or_none()

        return {
            "incident": {
                "incident_id": incident.incident_id if incident else None,
                "title": incident.title if incident else None,
                "severity": incident.severity if incident else None,
                "service": incident.service if incident else None,
                "incident_type": incident.incident_type if incident else None,
                "detected_at": incident.detected_at.isoformat() if incident and incident.detected_at else None,
            } if incident else None,
            "rca": {
                "root_cause": rca.root_cause if rca else None,
                "contributing_factors": rca.contributing_factors if rca else [],
                "confidence_score": rca.confidence_score if rca else None,
                "ai_analysis": rca.ai_analysis if rca else None,
            } if rca else None,
            "remediation": {
                "immediate_actions": remediation.immediate_actions if remediation else [],
                "long_term_fixes": remediation.long_term_fixes if remediation else [],
                "estimated_resolution_time": remediation.estimated_resolution_time if remediation else None,
                "ai_recommendation": remediation.ai_recommendation if remediation else None,
            } if remediation else None,
        }


@tool(
    description="Get business KPI metrics: transaction success rate, avg order value, top failing services.",
    schema={
        "type": "object",
        "properties": {
            "hours": {"type": "integer", "description": "Look-back hours for KPI calculation"},
        },
        "required": [],
    },
)
def get_business_kpis(hours: int = 24) -> Dict:
    """Returns business-level KPIs from Silver transaction data."""
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    with get_db() as db:
        txn_rows = db.execute(
            select(SilverTransaction).where(SilverTransaction.timestamp >= cutoff)
        ).scalars().all()

        total = len(txn_rows)
        if total == 0:
            return {"error": "no transaction data"}

        failed = sum(1 for t in txn_rows if t.is_failed)
        revenue = sum(t.amount for t in txn_rows if not t.is_failed)
        avg_order = revenue / (total - failed) if (total - failed) > 0 else 0

        by_method = {}
        for t in txn_rows:
            if t.is_failed:
                by_method[t.payment_method] = by_method.get(t.payment_method, 0) + 1

        return {
            "period_hours": hours,
            "total_transactions": total,
            "successful_transactions": total - failed,
            "failed_transactions": failed,
            "success_rate": round((total - failed) / total, 4),
            "total_revenue_usd": round(revenue, 2),
            "avg_order_value_usd": round(avg_order, 2),
            "failures_by_payment_method": by_method,
        }


@tool(
    description="Get aggregated metrics summary per service for the dashboard.",
    schema={
        "type": "object",
        "properties": {
            "hours": {"type": "integer", "description": "Look-back hours"},
        },
        "required": [],
    },
)
def get_service_health_summary(hours: int = 24) -> List[Dict]:
    """Returns per-service health snapshot for the past N hours."""
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    with get_db() as db:
        rows = db.execute(
            select(SilverMetric).where(SilverMetric.timestamp >= cutoff)
        ).scalars().all()

        by_service: Dict[str, List] = {}
        for r in rows:
            by_service.setdefault(r.service, []).append(r)

        import numpy as np
        result = []
        for service, srows in by_service.items():
            latencies = [r.avg_latency_ms for r in srows]
            error_rates = [r.error_rate for r in srows]
            cpus = [r.cpu_usage for r in srows]
            anomaly_count = sum(1 for r in srows if r.is_anomaly)
            result.append({
                "service": service,
                "avg_latency_ms": round(float(np.mean(latencies)), 2),
                "p95_latency_ms": round(float(np.percentile(latencies, 95)), 2),
                "avg_error_rate": round(float(np.mean(error_rates)), 4),
                "max_cpu_usage": round(float(np.max(cpus)), 2),
                "anomaly_count": anomaly_count,
                "health_status": "critical" if anomaly_count > 10 else "degraded" if anomaly_count > 3 else "healthy",
            })
        return sorted(result, key=lambda x: x["anomaly_count"], reverse=True)


@tool(
    description="Generate and save the HTML incident report with all data to the Gold dashboard folder.",
    schema={
        "type": "object",
        "properties": {
            "report_title": {"type": "string", "description": "Report title"},
            "incidents_json": {"type": "string", "description": "JSON string of all incidents"},
            "kpis_json": {"type": "string", "description": "JSON string of KPI data"},
            "service_health_json": {"type": "string", "description": "JSON string of service health data"},
            "executive_summary": {"type": "string", "description": "AI-written executive summary (2-3 paragraphs)"},
        },
        "required": ["report_title", "incidents_json", "kpis_json", "executive_summary"],
    },
)
def generate_html_report(
    report_title: str,
    incidents_json: str,
    kpis_json: str,
    executive_summary: str,
    service_health_json: str = "[]",
) -> Dict:
    """Generates a full HTML dashboard report and saves it to the Gold data path."""
    try:
        incidents = json.loads(incidents_json) if isinstance(incidents_json, str) else incidents_json
        kpis = json.loads(kpis_json) if isinstance(kpis_json, str) else kpis_json
        service_health = json.loads(service_health_json) if isinstance(service_health_json, str) else service_health_json
    except Exception as e:
        incidents, kpis, service_health = [], {}, []

    now = datetime.utcnow()
    gold_path = Path(settings.gold_data_path) / "dashboards"
    gold_path.mkdir(parents=True, exist_ok=True)
    filename = f"report_{now.strftime('%Y%m%d_%H%M%S')}.html"
    report_path = gold_path / filename

    p1_count = sum(1 for i in incidents if i.get("severity") == "P1")
    p2_count = sum(1 for i in incidents if i.get("severity") == "P2")

    # Build severity badge colours
    def sev_color(sev):
        return {"P1": "#dc2626", "P2": "#ea580c", "P3": "#ca8a04", "P4": "#16a34a"}.get(sev, "#6b7280")

    def health_color(status):
        return {"critical": "#dc2626", "degraded": "#ea580c", "healthy": "#16a34a"}.get(status, "#6b7280")

    incidents_rows = ""
    for inc in incidents:
        sev = inc.get("severity", "P3")
        color = sev_color(sev)
        incidents_rows += f"""
        <tr>
          <td><span style="background:{color};color:white;padding:2px 8px;border-radius:4px;font-weight:bold">{sev}</span></td>
          <td>{inc.get('incident_id','')}</td>
          <td>{inc.get('title','')}</td>
          <td>{inc.get('service','')}</td>
          <td>{inc.get('incident_type','').replace('_',' ').title()}</td>
          <td><span style="background:#6b7280;color:white;padding:2px 8px;border-radius:4px">{inc.get('status','')}</span></td>
          <td>{inc.get('detected_at','')[:16] if inc.get('detected_at') else ''}</td>
        </tr>"""

    service_rows = ""
    for svc in service_health:
        hc = health_color(svc.get("health_status", "healthy"))
        service_rows += f"""
        <tr>
          <td><strong>{svc.get('service','')}</strong></td>
          <td>{svc.get('avg_latency_ms','')} ms</td>
          <td>{svc.get('p95_latency_ms','')} ms</td>
          <td>{round(svc.get('avg_error_rate',0)*100,2)} %</td>
          <td>{svc.get('max_cpu_usage','')} %</td>
          <td>{svc.get('anomaly_count',0)}</td>
          <td><span style="background:{hc};color:white;padding:2px 8px;border-radius:4px">{svc.get('health_status','healthy').upper()}</span></td>
        </tr>"""

    success_rate_pct = round(kpis.get("success_rate", 0) * 100, 2) if isinstance(kpis, dict) else 0

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{report_title}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; }}
  .header {{ background: linear-gradient(135deg, #1e3a5f 0%, #0f172a 100%); padding: 40px; border-bottom: 2px solid #334155; }}
  .header h1 {{ font-size: 2rem; color: #60a5fa; margin-bottom: 8px; }}
  .header p {{ color: #94a3b8; font-size: 0.9rem; }}
  .container {{ max-width: 1400px; margin: 0 auto; padding: 32px; }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 32px; }}
  .kpi-card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; text-align: center; }}
  .kpi-card .value {{ font-size: 2rem; font-weight: 700; color: #60a5fa; }}
  .kpi-card .label {{ font-size: 0.8rem; color: #94a3b8; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.05em; }}
  .kpi-card.critical .value {{ color: #dc2626; }}
  .kpi-card.warning .value {{ color: #ea580c; }}
  .kpi-card.success .value {{ color: #16a34a; }}
  .section {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 24px; margin-bottom: 24px; }}
  .section h2 {{ font-size: 1.1rem; color: #60a5fa; margin-bottom: 16px; border-bottom: 1px solid #334155; padding-bottom: 12px; }}
  .summary-text {{ line-height: 1.8; color: #cbd5e1; white-space: pre-wrap; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.875rem; }}
  th {{ background: #0f172a; color: #94a3b8; padding: 10px 12px; text-align: left; font-weight: 600; text-transform: uppercase; font-size: 0.75rem; letter-spacing: 0.05em; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid #334155; color: #e2e8f0; }}
  tr:hover td {{ background: #0f172a; }}
  .footer {{ text-align: center; color: #475569; font-size: 0.8rem; padding: 32px; border-top: 1px solid #334155; }}
</style>
</head>
<body>
<div class="header">
  <h1>&#x26a1; {report_title}</h1>
  <p>Generated: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC &nbsp;|&nbsp; Powered by Claude Opus 5 &nbsp;|&nbsp; Medallion AIOps Platform</p>
</div>
<div class="container">

  <!-- KPI Summary -->
  <div class="kpi-grid">
    <div class="kpi-card {'critical' if p1_count > 0 else ''}">
      <div class="value">{len(incidents)}</div>
      <div class="label">Total Incidents</div>
    </div>
    <div class="kpi-card {'critical' if p1_count > 0 else ''}">
      <div class="value">{p1_count}</div>
      <div class="label">P1 Critical</div>
    </div>
    <div class="kpi-card {'warning' if p2_count > 0 else ''}">
      <div class="value">{p2_count}</div>
      <div class="label">P2 High</div>
    </div>
    <div class="kpi-card {'success' if success_rate_pct > 95 else 'warning'}">
      <div class="value">{success_rate_pct}%</div>
      <div class="label">Txn Success Rate</div>
    </div>
    <div class="kpi-card">
      <div class="value">${kpis.get('total_revenue_usd', 0):,.0f}</div>
      <div class="label">Revenue (24h)</div>
    </div>
    <div class="kpi-card">
      <div class="value">{kpis.get('total_transactions', 0):,}</div>
      <div class="label">Transactions</div>
    </div>
  </div>

  <!-- Executive Summary -->
  <div class="section">
    <h2>&#x1f4cb; Executive Summary</h2>
    <p class="summary-text">{executive_summary}</p>
  </div>

  <!-- Incident Table -->
  <div class="section">
    <h2>&#x1f6a8; Incident Log</h2>
    <table>
      <thead>
        <tr><th>Sev</th><th>ID</th><th>Title</th><th>Service</th><th>Type</th><th>Status</th><th>Detected</th></tr>
      </thead>
      <tbody>{incidents_rows or '<tr><td colspan="7" style="text-align:center;color:#94a3b8">No incidents in this period</td></tr>'}</tbody>
    </table>
  </div>

  <!-- Service Health -->
  <div class="section">
    <h2>&#x2764; Service Health Summary</h2>
    <table>
      <thead>
        <tr><th>Service</th><th>Avg Latency</th><th>P95 Latency</th><th>Error Rate</th><th>Max CPU</th><th>Anomalies</th><th>Status</th></tr>
      </thead>
      <tbody>{service_rows or '<tr><td colspan="7" style="text-align:center;color:#94a3b8">No data</td></tr>'}</tbody>
    </table>
  </div>

</div>
<div class="footer">
  Ecommerce AIOps &nbsp;|&nbsp; Medallion Architecture (Bronze &rarr; Silver &rarr; Gold) &nbsp;|&nbsp; Multi-Agent AI Incident Detection &amp; RCA
</div>
</body>
</html>"""

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)

    # Persist metadata
    with get_db() as db:
        db.add(GoldReport(
            incident_id="ALL",
            report_path=str(report_path),
            summary=executive_summary[:500],
            total_incidents=len(incidents),
            p1_count=p1_count,
            p2_count=p2_count,
        ))

    return {"status": "generated", "path": str(report_path), "filename": filename}


# ─────────────────────────── AGENT CLASS ─────────────────────────────────────

SYSTEM_PROMPT = """You are an AIOps Report Agent for an e-commerce platform.

Your job is to:
1. Retrieve all incidents from the Gold layer for the past 24 hours
2. Get service health metrics across all services
3. Get business KPIs (transaction success rate, revenue, failures)
4. Write an executive summary (3-4 paragraphs, suitable for engineering leadership)
   covering: overall platform health, most critical incidents, business impact,
   and recommended priorities
5. Generate and save the HTML dashboard report

Be specific and data-driven. Reference actual incident IDs, service names, and metrics.
Always call generate_html_report to save the final report."""


class ReportAgent(BaseAgent):
    def __init__(self, client: anthropic.Anthropic):
        super().__init__(
            client=client,
            model=settings.claude_model,
            tool_names=[
                "get_all_incidents",
                "get_incident_full_summary",
                "get_business_kpis",
                "get_service_health_summary",
                "generate_html_report",
            ],
        )

    def generate(self) -> str:
        user_prompt = (
            "Generate a complete AIOps incident report for the past 24 hours. "
            "Retrieve all incidents, service health, and KPIs. Write an executive summary "
            "covering platform health, critical incidents, and business impact. "
            "Then generate the HTML report with all data."
        )
        result = self.run(SYSTEM_PROMPT, user_prompt, max_iterations=25)
        print("  [ReportAgent] Report generated.")
        return result
