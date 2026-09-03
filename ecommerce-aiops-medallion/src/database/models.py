"""SQLAlchemy ORM models for all three Medallion layers."""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Text, Boolean, JSON, ForeignKey
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


# ─── BRONZE LAYER ────────────────────────────────────────────────────────────

class BronzeSystemMetric(Base):
    __tablename__ = "bronze_system_metrics"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ingested_at = Column(DateTime, default=datetime.utcnow)
    service = Column(String(100))
    timestamp = Column(DateTime)
    cpu_usage = Column(Float)
    memory_usage = Column(Float)
    request_count = Column(Integer)
    error_count = Column(Integer)
    avg_latency_ms = Column(Float)
    raw_payload = Column(JSON)


class BronzeTransaction(Base):
    __tablename__ = "bronze_transactions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ingested_at = Column(DateTime, default=datetime.utcnow)
    order_id = Column(String(50))
    user_id = Column(String(50))
    product_id = Column(String(50))
    amount = Column(Float)
    status = Column(String(30))
    payment_method = Column(String(30))
    timestamp = Column(DateTime)
    raw_payload = Column(JSON)


class BronzeLog(Base):
    __tablename__ = "bronze_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ingested_at = Column(DateTime, default=datetime.utcnow)
    service = Column(String(100))
    level = Column(String(10))
    message = Column(Text)
    endpoint = Column(String(200))
    status_code = Column(Integer)
    latency_ms = Column(Float)
    timestamp = Column(DateTime)
    raw_payload = Column(JSON)


class BronzeEvent(Base):
    __tablename__ = "bronze_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ingested_at = Column(DateTime, default=datetime.utcnow)
    event_type = Column(String(50))
    user_id = Column(String(50))
    session_id = Column(String(50))
    page = Column(String(100))
    action = Column(String(50))
    timestamp = Column(DateTime)
    raw_payload = Column(JSON)


# ─── SILVER LAYER ────────────────────────────────────────────────────────────

class SilverMetric(Base):
    __tablename__ = "silver_metrics"
    id = Column(Integer, primary_key=True, autoincrement=True)
    processed_at = Column(DateTime, default=datetime.utcnow)
    service = Column(String(100))
    timestamp = Column(DateTime)
    cpu_usage = Column(Float)
    memory_usage = Column(Float)
    request_count = Column(Integer)
    error_count = Column(Integer)
    avg_latency_ms = Column(Float)
    error_rate = Column(Float)          # Derived: error_count / request_count
    latency_zscore = Column(Float)      # Statistical anomaly score
    cpu_zscore = Column(Float)
    error_rate_zscore = Column(Float)
    is_anomaly = Column(Boolean, default=False)
    anomaly_type = Column(String(50))


class SilverLog(Base):
    __tablename__ = "silver_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    processed_at = Column(DateTime, default=datetime.utcnow)
    service = Column(String(100))
    level = Column(String(10))
    message = Column(Text)
    endpoint = Column(String(200))
    status_code = Column(Integer)
    latency_ms = Column(Float)
    timestamp = Column(DateTime)
    is_error = Column(Boolean, default=False)
    error_category = Column(String(50))   # timeout / 5xx / 4xx / payment_failure


class SilverTransaction(Base):
    __tablename__ = "silver_transactions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    processed_at = Column(DateTime, default=datetime.utcnow)
    order_id = Column(String(50))
    user_id = Column(String(50))
    product_id = Column(String(50))
    amount = Column(Float)
    status = Column(String(30))
    payment_method = Column(String(30))
    timestamp = Column(DateTime)
    is_failed = Column(Boolean, default=False)
    failure_reason = Column(String(100))


# ─── GOLD LAYER ──────────────────────────────────────────────────────────────

class GoldIncident(Base):
    __tablename__ = "gold_incidents"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    incident_id = Column(String(50), unique=True)
    title = Column(String(200))
    severity = Column(String(20))          # P1 / P2 / P3 / P4
    status = Column(String(20))            # open / investigating / resolved
    service = Column(String(100))
    incident_type = Column(String(50))     # latency_spike / error_surge / payment_failure
    detected_at = Column(DateTime)
    resolved_at = Column(DateTime, nullable=True)
    anomaly_details = Column(JSON)
    ai_classification = Column(Text)
    rcas = relationship("GoldRCA", back_populates="incident")


class GoldRCA(Base):
    __tablename__ = "gold_rca"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    incident_id = Column(String(50), ForeignKey("gold_incidents.incident_id"))
    root_cause = Column(Text)
    contributing_factors = Column(JSON)
    affected_services = Column(JSON)
    timeline = Column(JSON)
    confidence_score = Column(Float)
    ai_analysis = Column(Text)
    incident = relationship("GoldIncident", back_populates="rcas")
    remediations = relationship("GoldRemediation", back_populates="rca")


class GoldRemediation(Base):
    __tablename__ = "gold_remediations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    rca_id = Column(Integer, ForeignKey("gold_rca.id"))
    incident_id = Column(String(50))
    immediate_actions = Column(JSON)
    long_term_fixes = Column(JSON)
    runbook_steps = Column(JSON)
    estimated_resolution_time = Column(String(50))
    ai_recommendation = Column(Text)
    rca = relationship("GoldRCA", back_populates="remediations")


class GoldReport(Base):
    __tablename__ = "gold_reports"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    incident_id = Column(String(50))
    report_path = Column(String(500))
    summary = Column(Text)
    total_incidents = Column(Integer)
    p1_count = Column(Integer)
    p2_count = Column(Integer)
    avg_resolution_time_min = Column(Float)
