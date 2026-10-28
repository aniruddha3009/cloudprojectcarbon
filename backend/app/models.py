"""ORM tables. Every value shown in the UI is read from these tables."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, DecimalString


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SimClockRow(Base):
    __tablename__ = "sim_clock"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    epoch: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    current_slot: Mapped[int] = mapped_column(Integer, default=24)
    autoplay: Mapped[bool] = mapped_column(Boolean, default=False)
    speed_ms: Mapped[int] = mapped_column(Integer, default=800)
    scenario_active: Mapped[bool] = mapped_column(Boolean, default=False)
    scenario_end_slot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scenario_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    controller_state: Mapped[str] = mapped_column(String(32), default="NORMAL")
    band: Mapped[int] = mapped_column(Integer, default=0)
    next_job_number: Mapped[int] = mapped_column(Integer, default=1)
    run_id: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SettingRow(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class JobRow(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    workload: Mapped[str] = mapped_column(String(60), index=True)
    job_class: Mapped[str] = mapped_column(String(16), index=True)
    priority: Mapped[int] = mapped_column(Integer)
    power_w: Mapped[Decimal] = mapped_column(DecimalString)
    runtime_min: Mapped[int] = mapped_column(Integer)
    arrival_slot: Mapped[int] = mapped_column(Integer)
    deadline_slot: Mapped[int] = mapped_column(Integer)
    max_wait_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    simulate_failure: Mapped[bool] = mapped_column(Boolean, default=False)
    state: Mapped[str] = mapped_column(String(16), index=True)
    capacity: Mapped[Decimal] = mapped_column(DecimalString)
    work_done_min: Mapped[Decimal] = mapped_column(DecimalString)
    start_slot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    finish_slot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    energy_kwh: Mapped[Decimal] = mapped_column(DecimalString)
    emissions_g: Mapped[Decimal] = mapped_column(DecimalString)
    debt_g: Mapped[Decimal] = mapped_column(DecimalString)
    credit_g: Mapped[Decimal] = mapped_column(DecimalString)
    credit_earned_g: Mapped[Decimal] = mapped_column(DecimalString)
    deferred_by_controller: Mapped[bool] = mapped_column(Boolean, default=False)
    deferral_event_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    baseline_intensity: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    baseline_slot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    planned_start_slot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hold_until_slot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    manual_run: Mapped[bool] = mapped_column(Boolean, default=False)
    credit_void_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    deadline_missed: Mapped[bool] = mapped_column(Boolean, default=False)
    forced: Mapped[bool] = mapped_column(Boolean, default=False)
    deferral_count: Mapped[int] = mapped_column(Integer, default=0)
    throttle_count: Mapped[int] = mapped_column(Integer, default=0)
    last_decision_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    debt_booked: Mapped[bool] = mapped_column(Boolean, default=False)
    credit_settled: Mapped[bool] = mapped_column(Boolean, default=False)
    ledger_event_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DecisionRow(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slot: Mapped[int] = mapped_column(Integer, index=True)
    job_id: Mapped[str | None] = mapped_column(String(16), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(Text)
    policy: Mapped[str] = mapped_column(String(32))
    controller_state: Mapped[str] = mapped_column(String(32))
    intensity: Mapped[Decimal] = mapped_column(DecimalString)
    capacity: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    details: Mapped[Any] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExecutionRow(Base):
    """One execution attempt = one job running for (part of) one 15-minute slot."""

    __tablename__ = "execution_attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(16), ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    slot: Mapped[int] = mapped_column(Integer, index=True)
    capacity: Mapped[Decimal] = mapped_column(DecimalString)
    power_w: Mapped[Decimal] = mapped_column(DecimalString)
    minutes: Mapped[Decimal] = mapped_column(DecimalString)
    energy_kwh: Mapped[Decimal] = mapped_column(DecimalString)
    intensity: Mapped[Decimal] = mapped_column(DecimalString)
    intensity_source: Mapped[str] = mapped_column(String(32))
    emissions_g: Mapped[Decimal] = mapped_column(DecimalString)
    debt_g: Mapped[Decimal] = mapped_column(DecimalString)
    energy_source: Mapped[str] = mapped_column(String(48), default="ESTIMATED_MODEL")
    kernel_iterations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kernel_cpu_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    kernel_wall_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    host_power_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    host_power_source: Mapped[str | None] = mapped_column(String(48), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LedgerRow(Base):
    __tablename__ = "ledger_entries"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    event_id: Mapped[str] = mapped_column(String(16), unique=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    job_id: Mapped[str | None] = mapped_column(String(16), index=True, nullable=True)
    sim_time: Mapped[str] = mapped_column(String(32))
    recorded_at: Mapped[str] = mapped_column(String(40))
    energy_kwh: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    intensity_actual: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    intensity_baseline: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    amount_g: Mapped[Decimal] = mapped_column(DecimalString)
    balance_before_g: Mapped[Decimal] = mapped_column(DecimalString)
    balance_after_g: Mapped[Decimal] = mapped_column(DecimalString)
    reference_event_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    idem_key: Mapped[str] = mapped_column(String(64), unique=True)
    details: Mapped[Any] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)


class CarbonReadingRow(Base):
    __tablename__ = "carbon_readings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slot: Mapped[int] = mapped_column(Integer, index=True)
    sim_time: Mapped[str] = mapped_column(String(32))
    intensity: Mapped[Decimal] = mapped_column(DecimalString)
    source: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(64))
    region: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TimelineRow(Base):
    __tablename__ = "timeline_points"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slot: Mapped[int] = mapped_column(Integer, index=True)
    intensity: Mapped[Decimal] = mapped_column(DecimalString)
    intensity_source: Mapped[str] = mapped_column(String(32))
    green: Mapped[bool] = mapped_column(Boolean)
    balance_g: Mapped[Decimal] = mapped_column(DecimalString)
    accrued_g: Mapped[Decimal] = mapped_column(DecimalString)
    effective_debt_g: Mapped[Decimal] = mapped_column(DecimalString)
    cum_emissions_g: Mapped[Decimal] = mapped_column(DecimalString)
    cum_debt_g: Mapped[Decimal] = mapped_column(DecimalString)
    cum_credit_g: Mapped[Decimal] = mapped_column(DecimalString)
    band: Mapped[int] = mapped_column(Integer)
    controller_state: Mapped[str] = mapped_column(String(32))
    running: Mapped[int] = mapped_column(Integer)
    paused: Mapped[int] = mapped_column(Integer)
    queued: Mapped[int] = mapped_column(Integer)
    deferred: Mapped[int] = mapped_column(Integer)
    completed: Mapped[int] = mapped_column(Integer)
    throttled: Mapped[int] = mapped_column(Integer)


class TelemetryReadingRow(Base):
    __tablename__ = "telemetry_readings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    source: Mapped[str] = mapped_column(String(48))
    metric: Mapped[str] = mapped_column(String(48))
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(16))
    quality: Mapped[str] = mapped_column(String(24))
    details: Mapped[Any] = mapped_column(JSON, default=dict)


class ProviderSnapshotRow(Base):
    __tablename__ = "provider_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(64))
    region: Mapped[str] = mapped_column(String(64))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    period_start: Mapped[str] = mapped_column(String(32))
    values: Mapped[Any] = mapped_column(JSON)
    sources: Mapped[Any] = mapped_column(JSON)
    meta: Mapped[Any] = mapped_column(JSON, default=dict)


class GridReadingRow(Base):
    """A real reading (or forecast point) returned by the live grid provider. Never simulated."""

    __tablename__ = "grid_readings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)  # "actual" | "forecast"
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    intensity: Mapped[Decimal] = mapped_column(DecimalString)
    scope: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(64))
    dominant_fuel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExperimentRow(Base):
    __tablename__ = "experiment_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(16), index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    config: Mapped[Any] = mapped_column(JSON)
    results: Mapped[Any] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


Index("ix_decisions_slot_id", DecisionRow.slot, DecisionRow.id)
