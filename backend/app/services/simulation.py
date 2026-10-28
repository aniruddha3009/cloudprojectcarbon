"""Live controller service: database ⇄ engine bridge, autoplay loop, scenario.

For every tick the engine is rebuilt from the database, advanced one slot, and
every new decision, execution attempt, ledger record, carbon reading and
timeline point is persisted in the same transaction. A process-wide lock
serialises all mutations, so the hash chain can never fork.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import fields
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..core import accounting as acc
from ..core.carbon_curve import (PROFILE_DESCRIPTIONS, SLOT_MINUTES, SLOTS_PER_DAY, SLOTS_PER_HOUR, CarbonCurve,
                                 simulated_curve)
from ..core.config_model import ControllerConfig, GridEvent
from ..core.engine import TERMINAL_STATES, Engine, InvalidTransition, JobState, SimJob, slots_needed
from ..core.hashchain import GENESIS_HASH, verify_chain
from ..core.ledger import EventType, LedgerBook
from ..core.planner import Plan, build_plan
from ..core.policies import BAND_STATES, POLICIES, THROTTLE_TABLE, make_policy
from ..core.units import ONE, ZERO, D, q_g, to_float
from ..core.workloads import DEMO_JOBS, SCENARIO_END_SLOT, SCENARIO_START_SLOT, demo_sim_jobs
from ..db import Database
from ..models import (CarbonReadingRow, DecisionRow, ExecutionRow, JobRow, LedgerRow, ProviderSnapshotRow,
                      SettingRow, SimClockRow, TelemetryReadingRow, TimelineRow, utcnow)
from . import explain

log = logging.getLogger("carbon_debt.simulation")

# One-click simulated grid levels (gCO2e/kWh). Clearly simulated values, not readings of any real grid.
GRID_PRESETS = {"green": Decimal("120"), "coal": Decimal("650")}

# "Load sample processes": four processes that arrive at the current simulated time.
# name, application, class, priority, power W, runtime min, deadline after arrival (min)
SAMPLE_PROCESSES = [
    ("Hospital alert system", "hospital", "emergency", 1, 1500, 30, 60),
    ("Payroll report", "finance", "normal", 2, 800, 30, 45),
    ("Nightly data backup", "storage", "normal", 3, 1000, 60, 600),
    ("AI model training", "ml-research", "background", 4, 1200, 60, 720),
]

HORIZON_SLOTS = 3 * SLOTS_PER_DAY - 1
MAX_TELEMETRY_ROWS = 2000
UNCERTAINTY_NOTE = ("The planner treats the forecast curve as exact: forecast uncertainty is not modelled. "
                    "In simulation mode the forecast equals the realised curve; with a live snapshot the captured "
                    "forecast is replayed.")
JOB_FIELDS = [f.name for f in fields(SimJob) if f.name != "slot_minutes"]  # slot length is not persisted


class NotFound(LookupError):
    pass


class Conflict(ValueError):
    pass


class InvalidInput(ValueError):
    """Request is well-formed but not valid for the current mode (HTTP 422)."""


def today_epoch() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def row_to_job(row: JobRow, slot_minutes: Decimal = D(SLOT_MINUTES)) -> SimJob:
    data = {name: getattr(row, name) for name in JOB_FIELDS}
    data["ledger_event_ids"] = list(row.ledger_event_ids or [])
    return SimJob(**data, slot_minutes=slot_minutes)


def job_to_row(job: SimJob, row: JobRow) -> None:
    for name in JOB_FIELDS:
        value = getattr(job, name)
        if name == "ledger_event_ids":
            value = list(value)
        if getattr(row, name) != value:
            setattr(row, name, value)


def ledger_row_dict(row: LedgerRow) -> dict[str, Any]:
    return {
        "seq": row.seq, "event_id": row.event_id, "event_type": row.event_type, "job_id": row.job_id,
        "sim_time": row.sim_time, "recorded_at": row.recorded_at, "energy_kwh": row.energy_kwh,
        "intensity_actual": row.intensity_actual, "intensity_baseline": row.intensity_baseline,
        "amount_g": row.amount_g, "balance_before_g": row.balance_before_g, "balance_after_g": row.balance_after_g,
        "reference_event_id": row.reference_event_id, "idem_key": row.idem_key, "details": row.details or {},
        "prev_hash": row.prev_hash, "hash": row.hash,
    }


def _s(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


class SimulationService:
    mode = "simulation"
    slot_minutes: Decimal = D(SLOT_MINUTES)

    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------ lifecycle
    def start_background(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._autoplay_loop, name=f"{self.mode}-loop", daemon=True)
            self._thread.start()

    def stop_background(self) -> None:
        self._stop.set()

    def ensure_initialised(self) -> None:
        with self.lock, self.db.session() as s:
            self.clock(s)
            if s.get(SettingRow, "controller") is None:
                self.save_config(s, ControllerConfig())

    # --------------------------------------------------------------- config
    def config(self, s: Session) -> ControllerConfig:
        row = s.get(SettingRow, "controller")
        return ControllerConfig.model_validate(row.value) if row else ControllerConfig()

    def save_config(self, s: Session, cfg: ControllerConfig) -> None:
        row = s.get(SettingRow, "controller")
        value = cfg.model_dump(mode="json")
        if row is None:
            s.add(SettingRow(key="controller", value=value))
        else:
            row.value = value

    def clock(self, s: Session) -> SimClockRow:
        clock = s.get(SimClockRow, 1)
        if clock is None:
            clock = SimClockRow(id=1, epoch=today_epoch(), current_slot=SCENARIO_START_SLOT,
                                speed_ms=self.settings.autoplay_default_ms)
            s.add(clock)
            s.flush()
        if clock.epoch.tzinfo is None:  # SQLite drops tzinfo
            clock.epoch = clock.epoch.replace(tzinfo=timezone.utc)
        return clock

    def curve(self, s: Session, cfg: ControllerConfig) -> CarbonCurve:
        if cfg.carbon_source == "live_snapshot":
            snap = s.scalars(select(ProviderSnapshotRow).order_by(ProviderSnapshotRow.id.desc()).limit(1)).first()
            if snap is None:
                raise Conflict("carbon_source is live_snapshot but no provider snapshot has been captured")
            values = [Decimal(v) for v in snap.values]
            sources = list(snap.sources)
            if cfg.override.enabled:
                self._apply_override(values, sources, cfg)
            return CarbonCurve(values, sources, provider=snap.provider, region=snap.region)
        override = (cfg.override.start_hour, cfg.override.end_hour, cfg.override.intensity) if cfg.override.enabled else None
        events = [(e.from_slot, e.to_slot, e.intensity) for e in cfg.grid_events]
        return simulated_curve(cfg.profile, cfg.seed, cfg.noise_pct, days=3, override=override, events=events)

    @staticmethod
    def _apply_override(values: list[Decimal], sources: list[str], cfg: ControllerConfig) -> None:
        for slot in range(int(cfg.override.start_hour * SLOTS_PER_HOUR), int(cfg.override.end_hour * SLOTS_PER_HOUR)):
            if slot < len(values):
                values[slot] = cfg.override.intensity
                sources[slot] = "MANUAL_OVERRIDE"

    # ---------------------------------------------------------------- engine
    def ledger_book(self, s: Session) -> LedgerBook:
        rows = s.scalars(select(LedgerRow).order_by(LedgerRow.seq)).all()
        book = LedgerBook()
        for row in rows:
            book.idem_keys.add(row.idem_key)
            if row.event_type == EventType.DEBT_INCURRED:
                book.total_debt_g += row.amount_g
            elif row.event_type == EventType.CREDIT_VERIFIED:
                book.total_credit_applied_g += -row.amount_g
                book.total_credit_earned_g += Decimal(str((row.details or {}).get("credit_earned_g", "0")))
        if rows:
            book.last_seq, book.last_hash, book.balance_g = rows[-1].seq, rows[-1].hash, rows[-1].balance_after_g
        return book

    def build_engine(self, s: Session, with_kernel: bool = False) -> tuple[Engine, SimClockRow, ControllerConfig]:
        cfg = self.config(s)
        clock = self.clock(s)
        jobs = [row_to_job(r, self.slot_minutes) for r in s.scalars(select(JobRow)).all()]
        eng = Engine(cfg, self.curve(s, cfg), jobs, make_policy(cfg.policy), self.ledger_book(s),
                     now=clock.current_slot, epoch=clock.epoch, wall_clock=lambda: datetime.now(timezone.utc),
                     controller_state=clock.controller_state, slot_minutes=self.slot_minutes,
                     **self.engine_options(with_kernel))
        eng.band_value = clock.band
        return eng, clock, cfg

    def engine_options(self, with_kernel: bool) -> dict[str, Any]:
        """Simulation: modelled energy plus a small real CPU proxy kernel. Live mode overrides this."""
        return {"kernel": self._kernel if with_kernel else None}

    def _kernel(self, job: SimJob, capacity: Decimal) -> dict[str, Any]:
        """Real CPU proxy work: SHA-256 chain for kernel_ms × capacity of wall time."""
        budget_s = self.settings.kernel_ms * float(capacity) / 1000.0
        h = hashlib.sha256(job.id.encode())
        iterations = 0
        w0, c0 = time.perf_counter(), time.thread_time()
        while time.perf_counter() - w0 < budget_s:
            for _ in range(256):
                h = hashlib.sha256(h.digest())
            iterations += 256
        return {
            "iterations": iterations,
            "cpu_ms": round((time.thread_time() - c0) * 1000, 3),
            "wall_ms": round((time.perf_counter() - w0) * 1000, 3),
        }

    def persist(self, s: Session, eng: Engine, clock: SimClockRow) -> None:
        rows = {r.id: r for r in s.scalars(select(JobRow)).all()}
        for job in eng.jobs.values():
            job_to_row(job, rows[job.id])
        for d in eng.new_decisions:
            s.add(DecisionRow(slot=d.slot, job_id=d.job_id, action=d.action, reason=d.reason, policy=d.policy,
                              controller_state=d.controller_state, intensity=d.intensity, capacity=d.capacity,
                              details=d.details))
        s.flush()
        for seg in eng.new_segments:
            k = seg.kernel or {}
            s.add(ExecutionRow(job_id=seg.job_id, slot=seg.slot, capacity=seg.capacity, power_w=seg.power_w,
                               minutes=seg.minutes, energy_kwh=seg.energy_kwh, intensity=seg.intensity,
                               intensity_source=seg.intensity_source, emissions_g=seg.emissions_g, debt_g=seg.debt_g,
                               energy_source=seg.energy_source,
                               kernel_iterations=k.get("iterations"), kernel_cpu_ms=k.get("cpu_ms"),
                               kernel_wall_ms=k.get("wall_ms"), host_power_w=k.get("host_power_w"),
                               host_power_source=k.get("host_power_source")))
        for rec in eng.ledger.new_records:
            s.add(LedgerRow(**{k: v for k, v in rec.as_dict().items()}))
        for p in eng.new_timeline:
            s.add(TimelineRow(**{f.name: getattr(p, f.name) for f in fields(p)}))
            s.add(CarbonReadingRow(slot=p.slot, sim_time=eng.iso(p.slot), intensity=p.intensity,
                                   source=p.intensity_source, provider=eng.curve.provider, region=eng.curve.region))
        clock.current_slot = eng.now
        clock.controller_state = eng.controller_state
        clock.band = eng.band_value
        if eng.last_plan is not None:
            self._save_setting(s, "last_plan", self.plan_dict(eng, eng.last_plan))
        eng.new_decisions.clear()
        eng.new_segments.clear()
        eng.new_timeline.clear()
        eng.ledger.new_records.clear()

    @staticmethod
    def _save_setting(s: Session, key: str, value: Any) -> None:
        row = s.get(SettingRow, key)
        if row is None:
            s.add(SettingRow(key=key, value=value))
        else:
            row.value = value

    # ------------------------------------------------------------- stepping
    def tick(self, slots: int = 1) -> dict[str, Any]:
        with self.lock, self.db.session() as s:
            eng, clock, _ = self.build_engine(s, with_kernel=True)
            done = 0
            for _ in range(slots):
                if eng.now >= HORIZON_SLOTS:
                    break
                eng.step()
                done += 1
            new_ledger = len(eng.ledger.new_records)
            self.persist(s, eng, clock)
            if clock.scenario_active and clock.scenario_end_slot is not None and clock.current_slot >= clock.scenario_end_slot:
                clock.scenario_active = False
                clock.autoplay = False
            if clock.current_slot >= HORIZON_SLOTS:
                clock.autoplay = False
            return {"advanced": done, "slot": clock.current_slot, "sim_time": eng.iso(clock.current_slot),
                    "new_ledger_events": new_ledger, "at_horizon": clock.current_slot >= HORIZON_SLOTS}

    def set_autoplay(self, enabled: bool, speed_ms: int | None = None) -> dict[str, Any]:
        with self.lock, self.db.session() as s:
            clock = self.clock(s)
            if enabled and clock.current_slot >= HORIZON_SLOTS:
                raise Conflict("simulation horizon reached; reset the demo to continue")
            clock.autoplay = enabled
            if speed_ms is not None:
                clock.speed_ms = speed_ms
            if not enabled:
                clock.scenario_active = False
            return {"autoplay": clock.autoplay, "speed_ms": clock.speed_ms}

    def _autoplay_loop(self) -> None:
        while not self._stop.is_set():
            delay = 0.5
            try:
                with self.db.session() as s:
                    clock = self.clock(s)
                    playing, speed = clock.autoplay, clock.speed_ms
                if playing:
                    started = time.perf_counter()
                    self.tick(1)
                    delay = max(0.05, speed / 1000.0 - (time.perf_counter() - started))
            except Exception:  # pragma: no cover - keep the loop alive, surface in logs
                log.exception("autoplay tick failed; autoplay stopped")
                try:
                    with self.lock, self.db.session() as s:
                        self.clock(s).autoplay = False
                except Exception:
                    pass
            self._stop.wait(delay)

    # ----------------------------------------------------------- demo reset
    def reset(self, slot: int = SCENARIO_START_SLOT) -> None:
        with self.lock, self.db.session() as s:
            for model in (ExecutionRow, DecisionRow, LedgerRow, TimelineRow, CarbonReadingRow, JobRow):
                s.execute(delete(model))
            s.execute(delete(SettingRow).where(SettingRow.key == "last_plan"))
            clock = self.clock(s)
            clock.epoch = today_epoch()
            clock.current_slot = slot
            clock.autoplay = False
            clock.scenario_active = False
            clock.scenario_end_slot = None
            clock.controller_state = "NORMAL"
            clock.band = 0
            clock.next_job_number = 1
            clock.run_id += 1
            self._clear_grid_events(s)
        log.info("demo data reset", extra={"slot": slot})

    def _clear_grid_events(self, s: Session) -> None:
        """A reset restores the normal simulated daily pattern (predictable starting point)."""
        cfg = self.config(s)
        if cfg.grid_events:
            self.save_config(s, cfg.model_copy(update={"grid_events": []}))

    def load_samples(self) -> list[str]:
        """Reset, then add four sample processes that arrive now (06:00)."""
        self.reset(SCENARIO_START_SLOT)
        ids = []
        for name, app, cls, prio, power, runtime, deadline in SAMPLE_PROCESSES:
            res = self.create_job({"name": name, "workload": app, "job_class": cls, "priority": prio,
                                   "power_w": power, "runtime_min": runtime, "deadline_offset_min": deadline,
                                   "arrival_offset_min": 0})
            ids.append(res["job"]["id"])
        return ids

    def set_grid(self, preset: str, intensity: Decimal | None, hours: float) -> dict[str, Any]:
        """Set the simulated grid level from the current slot for ``hours``; 'normal' restores the daily pattern.

        Earlier settings are kept for the slots already played, so recorded history never changes.
        """
        if preset in GRID_PRESETS:
            intensity = GRID_PRESETS[preset]
        elif preset == "custom":
            if intensity is None:
                raise InvalidInput("enter a carbon intensity in gCO₂e/kWh")
        elif preset != "normal":
            raise InvalidInput(f"unknown grid preset {preset}")
        with self.lock, self.db.session() as s:
            cfg = self.config(s)
            clock = self.clock(s)
            t = clock.current_slot
            kept = [e.model_copy(update={"to_slot": min(e.to_slot, t)}) for e in cfg.grid_events if e.from_slot < t]
            end = None
            if preset != "normal":
                end = min(t + max(1, round(hours * SLOTS_PER_HOUR)), HORIZON_SLOTS + 1)
                kept.append(GridEvent(from_slot=t, to_slot=end, intensity=intensity, label=preset))
            cfg = ControllerConfig.model_validate({**cfg.model_dump(mode="json"),
                                                   "grid_events": [e.model_dump(mode="json") for e in kept[-100:]]})
            self.save_config(s, cfg)
            reason = ("Simulated grid returned to its normal daily pattern." if preset == "normal" else
                      f"Simulated grid set to {preset.replace('coal', 'coal-heavy')} "
                      f"({intensity.normalize():f} gCO₂e/kWh) from {self.slot_label(t)} to {self.slot_label(end)}.")
            s.add(DecisionRow(slot=t, job_id=None, action="GRID_CHANGED", reason=reason, policy=cfg.policy,
                              controller_state=clock.controller_state, intensity=Decimal(intensity or 0),
                              details={"preset": preset, "until_slot": end}))
            return {"preset": preset, "intensity": to_float(intensity), "from_slot": t, "until_slot": end,
                    "until_time": self._time(clock, end), "message": reason}

    def grid_override_status(self, s: Session, cfg: ControllerConfig, t: int) -> dict[str, Any] | None:
        for e in reversed(cfg.grid_events):
            if e.from_slot <= t < e.to_slot:
                return {"preset": e.label, "intensity": to_float(e.intensity), "until_slot": e.to_slot,
                        "until_label": self.slot_label(e.to_slot)}
        return None

    def load_demo(self) -> list[str]:
        self.reset(SCENARIO_START_SLOT)
        with self.lock, self.db.session() as s:
            clock = self.clock(s)
            ids = []
            for job in demo_sim_jobs():
                row = JobRow(id=job.id)
                job_to_row(job, row)
                s.add(row)
                ids.append(job.id)
            clock.next_job_number = len(ids) + 1
            return ids

    def run_scenario(self, mode: str, speed_ms: int | None = None) -> dict[str, Any]:
        cfg_note = None
        with self.db.session() as s:
            cfg = self.config(s)
            if cfg.carbon_source != "simulated" or cfg.profile != "solar_midday":
                cfg_note = ("The scenario is designed for the simulated solar_midday profile; with the current carbon "
                            "source/profile the green window may differ.")
        self.load_demo()
        with self.lock, self.db.session() as s:
            clock = self.clock(s)
            clock.scenario_active = True
            clock.scenario_end_slot = SCENARIO_END_SLOT
            clock.scenario_started_at = utcnow()
            clock.speed_ms = speed_ms or clock.speed_ms
            clock.autoplay = mode == "animated"
        if mode == "instant":
            self.tick(SCENARIO_END_SLOT - SCENARIO_START_SLOT)
        result = self.scenario_status()
        result["note"] = cfg_note
        return result

    # --------------------------------------------------------------- jobs
    def create_job(self, data: dict[str, Any]) -> dict[str, Any]:
        with self.lock, self.db.session() as s:
            key = data.get("idempotency_key")
            if key:
                existing = s.scalars(select(JobRow).where(JobRow.idempotency_key == key)).first()
                if existing is not None:
                    return {"job": self.job_summary(existing, self.clock(s)), "duplicate": True}
            if s.scalar(select(func.count()).select_from(JobRow)) >= self.settings.max_jobs:
                raise Conflict(f"job limit of {self.settings.max_jobs} reached; reset the demo")
            clock = self.clock(s)
            now = clock.current_slot
            self.validate_job_times(data)
            sm = self.slot_minutes
            arrival = now + int(D(data.get("arrival_offset_min") or 0) / sm)
            runtime = int(data["runtime_min"])
            need = slots_needed(D(runtime), ONE, sm)
            deadline = arrival + int(D(data["deadline_offset_min"]) / sm)
            if deadline < arrival + need:
                raise Conflict(f"deadline is infeasible: the job needs {runtime} min but only "
                               f"{(deadline - arrival) * sm} min are available after arrival")
            if arrival > self.horizon_slot(clock) - need:
                raise Conflict("arrival is beyond the simulation horizon")
            job_id = f"J-{clock.next_job_number:04d}"
            clock.next_job_number += 1
            job = SimJob(id=job_id, name=data["name"].strip(), workload=data["workload"].strip(),
                         job_class=data["job_class"], priority=int(data["priority"]), power_w=D(data["power_w"]),
                         runtime_min=runtime, arrival_slot=arrival, deadline_slot=deadline,
                         max_wait_min=data.get("max_wait_min"), simulate_failure=bool(data.get("simulate_failure")))
            row = JobRow(id=job_id, idempotency_key=key)
            job_to_row(job, row)
            s.add(row)
            s.flush()
            return {"job": self.job_summary(row, clock), "duplicate": False}

    def job_action(self, job_id: str, action: str, hold_minutes: int | None = None) -> dict[str, Any]:
        with self.lock, self.db.session() as s:
            eng, clock, _ = self.build_engine(s)
            job = eng.jobs.get(job_id)
            if job is None:
                raise NotFound(f"job {job_id} not found")
            try:
                if action == "cancel":
                    eng.operator_cancel(job)
                elif action == "run":
                    eng.operator_run(job)
                    eng.log(job, "OPERATOR_RUN_REQUESTED", "Operator requested immediate execution; starts at the next tick.")
                elif action == "defer":
                    minutes = hold_minutes or 60
                    eng.operator_hold(job, eng.now + max(1, int(D(minutes) / self.slot_minutes)))
                else:
                    raise Conflict(f"unknown action {action}")
            except InvalidTransition as exc:
                raise Conflict(str(exc)) from exc
            self.persist(s, eng, clock)
            row = s.get(JobRow, job_id)
            return self.job_summary(row, clock)

    # ------------------------------------------------------------ reading
    def _time(self, clock: SimClockRow, slot: int | None) -> str | None:
        if slot is None:
            return None
        return (clock.epoch + timedelta(minutes=float(self.slot_minutes) * slot)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def slot_label(self, slot: int | None) -> str | None:
        """Clock label used in plain-English reasons (simulated 15-minute clock)."""
        if slot is None:
            return None
        day, rem = divmod(slot * SLOT_MINUTES, 24 * 60)
        label = f"{rem // 60:02d}:{rem % 60:02d}"
        return label if day == 0 else f"{label} (day {day + 1})"

    def _explain(self, row: JobRow, clock: SimClockRow, last: DecisionRow | None,
                 cfg: ControllerConfig | None) -> dict[str, Any]:
        action = last.action if last is not None else explain.last_action(row.last_decision_key)
        now = clock.current_slot
        return {
            "status_label": explain.status_label(row.state, now, row.arrival_slot, row.planned_start_slot),
            "last_action": action,
            "plain_reason": explain.plain_reason(
                state=row.state, action=action, reason=last.reason if last is not None else row.last_reason,
                policy=last.policy if last is not None else (cfg.policy if cfg else None),
                intensity=last.intensity if last is not None else None,
                green_threshold=cfg.green_threshold if cfg else None,
                debt_threshold=cfg.debt_intensity_threshold if cfg else None,
                capacity=row.capacity, deadline_missed=row.deadline_missed, manual_run=row.manual_run,
                planned_slot=row.planned_start_slot, hold_slot=row.hold_until_slot, arrival_slot=row.arrival_slot,
                at=self.slot_label, now=now),
            "decision_intensity": to_float(last.intensity) if last is not None else None,
        }

    def _last_decisions(self, s: Session, job_ids: list[str]) -> dict[str, DecisionRow]:
        last: dict[str, DecisionRow] = {}
        if job_ids:
            for d in s.scalars(select(DecisionRow).where(DecisionRow.job_id.in_(job_ids)).order_by(DecisionRow.id)).all():
                last[d.job_id] = d
        return last

    def job_summary(self, row: JobRow, clock: SimClockRow, last: DecisionRow | None = None,
                    cfg: ControllerConfig | None = None) -> dict[str, Any]:
        t = self._time
        waiting = None
        if row.start_slot is not None:
            waiting = float((row.start_slot - row.arrival_slot) * self.slot_minutes)
        delay = None
        if row.finish_slot is not None and row.state == JobState.COMPLETED:
            delay = float((row.finish_slot - row.arrival_slot) * self.slot_minutes - row.runtime_min)
        return {
            "id": row.id, "name": row.name, "workload": row.workload, "job_class": row.job_class,
            "priority": row.priority, "state": row.state, "power_w": to_float(row.power_w),
            "runtime_min": row.runtime_min, "energy_estimate_kwh": to_float(acc.energy_kwh(row.power_w, row.runtime_min)),
            "arrival_slot": row.arrival_slot, "arrival_time": t(clock, row.arrival_slot),
            "deadline_slot": row.deadline_slot, "deadline_time": t(clock, row.deadline_slot),
            "start_time": t(clock, row.start_slot), "finish_time": t(clock, row.finish_slot),
            "start_slot": row.start_slot, "finish_slot": row.finish_slot,
            "planned_start_time": t(clock, row.planned_start_slot), "planned_start_slot": row.planned_start_slot,
            "hold_until_time": t(clock, row.hold_until_slot),
            "capacity": to_float(row.capacity), "progress": to_float(min(ONE, row.work_done_min / D(row.runtime_min))),
            "energy_kwh": to_float(row.energy_kwh), "emissions_g": to_float(row.emissions_g),
            "debt_g": to_float(row.debt_g), "credit_g": to_float(row.credit_g), "credit_earned_g": to_float(row.credit_earned_g),
            "deferred_by_controller": row.deferred_by_controller, "baseline_intensity": to_float(row.baseline_intensity),
            "deadline_missed": row.deadline_missed, "forced": row.forced, "deferral_count": row.deferral_count,
            "throttle_count": row.throttle_count, "max_wait_min": row.max_wait_min,
            "simulate_failure": row.simulate_failure, "last_reason": row.last_reason,
            "waiting_min": waiting, "delay_min": delay, "manual_run_pending": row.manual_run,
            "available_actions": self._actions(row),
            **self._explain(row, clock, last, cfg),
        }

    @staticmethod
    def _actions(row: JobRow) -> list[str]:
        if row.state in (JobState.QUEUED, JobState.DEFERRED):
            return ["run", "defer", "cancel"]
        if row.state in (JobState.RUNNING, JobState.PAUSED):
            return ["cancel"]
        return []

    def list_jobs(self, state: str | None = None, job_class: str | None = None, q: str | None = None) -> list[dict[str, Any]]:
        with self.db.session() as s:
            clock = self.clock(s)
            stmt = select(JobRow).order_by(JobRow.arrival_slot, JobRow.id)
            if state:
                stmt = stmt.where(JobRow.state == state)
            if job_class:
                stmt = stmt.where(JobRow.job_class == job_class)
            rows = s.scalars(stmt).all()
            if q:
                needle = q.lower()
                rows = [r for r in rows if needle in r.name.lower() or needle in r.workload.lower() or needle in r.id.lower()]
            cfg = self.config(s)
            last = self._last_decisions(s, [r.id for r in rows])
            return [self.job_summary(r, clock, last.get(r.id), cfg) for r in rows]

    def job_detail(self, job_id: str) -> dict[str, Any]:
        with self.db.session() as s:
            row = s.get(JobRow, job_id)
            if row is None:
                raise NotFound(f"job {job_id} not found")
            clock = self.clock(s)
            decisions = s.scalars(select(DecisionRow).where(DecisionRow.job_id == job_id).order_by(DecisionRow.id)).all()
            execs = s.scalars(select(ExecutionRow).where(ExecutionRow.job_id == job_id).order_by(ExecutionRow.slot)).all()
            ledger = s.scalars(select(LedgerRow).where(LedgerRow.job_id == job_id).order_by(LedgerRow.seq)).all()
            return {
                "job": self.job_summary(row, clock, decisions[-1] if decisions else None, self.config(s)),
                "decisions": [self.decision_dict(d, clock) for d in decisions],
                "executions": [self.exec_dict(e, clock) for e in execs],
                "ledger": [self.ledger_dict(r) for r in ledger],
                "receipt": self._receipt(row, clock, decisions, execs, ledger) if row.state in TERMINAL_STATES else None,
            }

    def receipt(self, job_id: str) -> dict[str, Any]:
        detail = self.job_detail(job_id)
        if detail["receipt"] is None:
            raise Conflict("a receipt is issued once the job has completed, failed or been cancelled")
        return detail["receipt"]

    def _receipt(self, row: JobRow, clock: SimClockRow, decisions, execs, ledger) -> dict[str, Any]:
        cfg = None
        with self.db.session() as s:
            cfg = self.config(s)
        sources = sorted({e.intensity_source for e in execs})
        start_decision = next((d for d in decisions if d.action.endswith("START")), None)
        defer_decision = next((d for d in decisions if d.action == "DEFER"), None)
        net = q_g(row.debt_g - row.credit_g)
        kernel_cpu = sum((e.kernel_cpu_ms or 0.0) for e in execs)
        host_samples = [e.host_power_w for e in execs if e.host_power_w is not None]
        avg_int = q_g(row.emissions_g / row.energy_kwh) if row.energy_kwh > ZERO else None
        return {
            "receipt_id": f"RCPT-{row.id}",
            "issued_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "job": {"id": row.id, "name": row.name, "workload": row.workload, "class": row.job_class,
                    "priority": row.priority, "outcome": row.state},
            "energy": {"kwh": _s(row.energy_kwh), "full_speed_estimate_kwh": _s(acc.energy_kwh(row.power_w, row.runtime_min)),
                       "declared_power_w": _s(row.power_w), "execution_slots": len(execs),
                       "source": "ESTIMATED — declared power × runtime, static/dynamic throttle model "
                                 f"(static fraction {cfg.static_power_fraction})"},
            "grid": {"avg_intensity_g_per_kwh": _s(avg_int), "sources": sources,
                     "baseline_intensity_g_per_kwh": _s(row.baseline_intensity)},
            "carbon": {"gross_emissions_g": _s(row.emissions_g), "policy_debt_g": _s(row.debt_g),
                       "credit_earned_g": _s(row.credit_earned_g), "credit_applied_g": _s(row.credit_g),
                       "net_policy_balance_impact_g": _s(net),
                       "debt_threshold_g_per_kwh": _s(cfg.debt_intensity_threshold)},
            "scheduling": {
                "arrival": self._time(clock, row.arrival_slot), "start": self._time(clock, row.start_slot),
                "finish": self._time(clock, row.finish_slot), "deferrals": row.deferral_count,
                "throttle_actions": row.throttle_count, "deferred_by_controller": row.deferred_by_controller,
                "start_decision": start_decision.reason if start_decision else None,
                "deferral_decision": defer_decision.reason if defer_decision else None,
                "credit_void_reason": row.credit_void_reason,
            },
            "deadline": {"deadline": self._time(clock, row.deadline_slot), "met": not row.deadline_missed},
            "execution_evidence": {
                "proxy_kernel_cpu_ms": round(kernel_cpu, 3),
                "host_power_samples_w": host_samples[:20],
                "note": "The proxy kernel is real CPU work executed by the backend for each job-slot; it is not the "
                        "workload's energy. Host power (if any) is whole-laptop telemetry, not attributed to the job.",
            },
            "ledger": [{"event_id": r.event_id, "event_type": r.event_type, "amount_g": _s(r.amount_g),
                        "hash": r.hash, "prev_hash": r.prev_hash} for r in ledger],
            "limitations": [
                "Energy is an estimate from declared power, not a hardware meter.",
                "Carbon intensity is " + (" / ".join(sources) or "n/a") + "; simulated values are illustrative.",
                "Debt is policy-defined (above the threshold), not the job's total footprint.",
                "Credits reward avoided future emissions against a recorded baseline; they do not remove past emissions.",
            ],
        }

    def decision_dict(self, d: DecisionRow, clock: SimClockRow) -> dict[str, Any]:
        return {"id": d.id, "slot": d.slot, "sim_time": self._time(clock, d.slot), "job_id": d.job_id,
                "action": d.action, "reason": d.reason, "policy": d.policy, "controller_state": d.controller_state,
                "intensity": to_float(d.intensity), "capacity": to_float(d.capacity), "details": d.details or {}}

    def exec_dict(self, e: ExecutionRow, clock: SimClockRow) -> dict[str, Any]:
        return {"slot": e.slot, "sim_time": self._time(clock, e.slot), "capacity": to_float(e.capacity),
                "power_w": to_float(e.power_w), "minutes": to_float(e.minutes), "energy_kwh": to_float(e.energy_kwh),
                "intensity": to_float(e.intensity), "intensity_source": e.intensity_source,
                "emissions_g": to_float(e.emissions_g), "debt_g": to_float(e.debt_g), "energy_source": e.energy_source,
                "kernel_iterations": e.kernel_iterations, "kernel_cpu_ms": e.kernel_cpu_ms,
                "kernel_wall_ms": e.kernel_wall_ms, "host_power_w": e.host_power_w,
                "host_power_source": e.host_power_source}

    @staticmethod
    def ledger_dict(r: LedgerRow) -> dict[str, Any]:
        d = ledger_row_dict(r)
        for k in ("energy_kwh", "intensity_actual", "intensity_baseline", "amount_g", "balance_before_g", "balance_after_g"):
            d[k] = _s(d[k])
        return d

    def decisions(self, limit: int = 100, job_id: str | None = None, action: str | None = None) -> list[dict[str, Any]]:
        with self.db.session() as s:
            clock = self.clock(s)
            stmt = select(DecisionRow).order_by(DecisionRow.id.desc()).limit(limit)
            if job_id:
                stmt = stmt.where(DecisionRow.job_id == job_id)
            if action:
                stmt = stmt.where(DecisionRow.action == action)
            return [self.decision_dict(d, clock) for d in s.scalars(stmt).all()]

    def ledger(self, event_type: str | None = None, job_id: str | None = None) -> list[dict[str, Any]]:
        with self.db.session() as s:
            stmt = select(LedgerRow).order_by(LedgerRow.seq)
            if event_type:
                stmt = stmt.where(LedgerRow.event_type == event_type)
            if job_id:
                stmt = stmt.where(LedgerRow.job_id == job_id)
            return [self.ledger_dict(r) for r in s.scalars(stmt).all()]

    def verify_ledger(self, expected_head: str | None = None) -> dict[str, Any]:
        with self.db.session() as s:
            rows = s.scalars(select(LedgerRow).order_by(LedgerRow.seq)).all()
            result = verify_chain([ledger_row_dict(r) for r in rows], expected_head).as_dict()
            result["verified_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            return result

    def tamper_demo(self, seq: int | None = None, field_name: str = "amount_g") -> dict[str, Any]:
        """Modify a COPY of one record in memory and show that verification catches it."""
        allowed = {"amount_g", "intensity_baseline", "energy_kwh", "job_id", "delete", "reorder"}
        if field_name not in allowed:
            raise Conflict(f"field must be one of {sorted(allowed)}")
        with self.db.session() as s:
            rows = s.scalars(select(LedgerRow).order_by(LedgerRow.seq)).all()
            records = [ledger_row_dict(r) for r in rows]
        if len(records) < 2:
            raise Conflict("the ledger needs at least two entries; run the scenario first")
        target = seq or next((r["seq"] for r in records if r["event_type"] == EventType.DEBT_INCURRED), records[0]["seq"])
        if not 1 <= target <= len(records):
            raise Conflict(f"seq must be between 1 and {len(records)}")
        copy = [dict(r) for r in records]
        idx = target - 1
        before = after = None
        if field_name == "delete":
            removed = copy.pop(idx)
            before, after = removed["event_id"], "(record removed)"
        elif field_name == "reorder":
            j = idx + 1 if idx + 1 < len(copy) else idx - 1
            copy[idx], copy[j] = copy[j], copy[idx]
            before, after = f"seq {copy[j]['seq']} before {copy[idx]['seq']}", "swapped"
        elif field_name == "job_id":
            before = copy[idx]["job_id"]
            copy[idx]["job_id"] = "J-9999"
            after = "J-9999"
        else:
            original = copy[idx][field_name] or Decimal("0")
            before = str(original)
            changed = q_g(Decimal(original) * Decimal("0.5")) if field_name == "amount_g" else Decimal(original) + 100
            copy[idx][field_name] = changed
            after = str(changed)
        original_result = verify_chain(records).as_dict()
        tampered_result = verify_chain(copy).as_dict()
        return {
            "target_seq": target, "field": field_name, "before": before, "after": after,
            "original": original_result, "tampered_copy": tampered_result,
            "database_modified": False,
            "explanation": "Only an in-memory copy was altered. Recomputing the SHA-256 chain exposes the change at "
                           f"seq {tampered_result['first_bad_seq']}. A hash chain proves integrity relative to a trusted "
                           "head hash; an attacker who can rewrite every row could recompute all hashes, so the head "
                           "must be checkpointed externally.",
        }

    # ------------------------------------------------------------- overview
    def plan_dict(self, eng: Engine, plan: Plan) -> dict[str, Any]:
        return {
            "slot": plan.slot, "sim_time": eng.iso(plan.slot), "start_debt_g": to_float(plan.start_debt_g),
            "peak_g": to_float(plan.peak_g), "end_balance_g": to_float(plan.end_balance_g),
            "repayable_g": to_float(plan.repayable_g), "projected_new_debt_g": to_float(plan.projected_new_debt_g),
            "horizon_end_slot": plan.horizon_end,
            "projection": [{"slot": s_, "sim_time": eng.iso(s_), "balance_g": to_float(b)} for s_, b in plan.projection],
            "placements": [{
                "job_id": p.job.id, "name": p.job.name, "job_class": p.job.job_class, "priority": p.job.priority,
                "start_slot": p.start, "start_time": eng.iso(p.start) if p.start is not None else None,
                "window_avg": to_float(p.window_avg), "now_avg": to_float(p.now_avg), "green": p.green,
                "forced": p.forced, "deliberate": p.deliberate, "est_savings_g": to_float(p.est_savings_g),
                "est_debt_g": to_float(p.est_debt_g), "est_credit_g": to_float(p.est_credit_g), "reason": p.reason,
                "deadline_time": eng.iso(p.job.deadline_slot),
            } for p in plan.placements],
            "uncertainty_note": UNCERTAINTY_NOTE,
        }

    def state(self) -> dict[str, Any]:
        with self.db.session() as s:
            eng, clock, cfg = self.build_engine(s)
            t = clock.current_slot
            timeline = s.scalars(select(TimelineRow).order_by(TimelineRow.slot)).all()
            peak = max((r.effective_debt_g for r in timeline), default=ZERO)
            counts: dict[str, int] = {}
            for job in eng.jobs.values():
                counts[job.state] = counts.get(job.state, 0) + 1
            recent = s.scalars(select(DecisionRow).order_by(DecisionRow.id.desc()).limit(8)).all()
            ledger_count = s.scalar(select(func.count()).select_from(LedgerRow)) or 0
            band = clock.band
            return {
                "clock": {"epoch": clock.epoch.strftime("%Y-%m-%dT%H:%M:%SZ"), "slot": t, "sim_time": eng.iso(t),
                          "label": eng.hhmm(t), "autoplay": clock.autoplay, "speed_ms": clock.speed_ms,
                          "scenario_active": clock.scenario_active, "scenario_end_slot": clock.scenario_end_slot,
                          "horizon_slot": self.horizon_slot(clock), "slot_minutes": float(self.slot_minutes)},
                "carbon": {"intensity": to_float(eng.intensity(t)), "source": eng.curve.source_at(t),
                           "provider": eng.curve.provider, "region": eng.curve.region, "green": eng.is_green(t),
                           "green_threshold": to_float(cfg.green_threshold),
                           "debt_threshold": to_float(cfg.debt_intensity_threshold),
                           "mode": "SIMULATED" if cfg.carbon_source == "simulated" else "LIVE_SNAPSHOT",
                           "profile": cfg.profile, "manual": self.grid_override_status(s, cfg, t)},
                "ledger": {"balance_g": to_float(eng.ledger.balance_g), "accrued_g": to_float(eng.accrued_debt()),
                           "effective_g": to_float(eng.effective_debt()),
                           "total_debt_g": to_float(eng.ledger.total_debt_g),
                           "credits_applied_g": to_float(eng.ledger.total_credit_applied_g),
                           "credits_earned_g": to_float(eng.ledger.total_credit_earned_g),
                           "peak_effective_g": to_float(peak), "head_hash": eng.ledger.last_hash,
                           "entries": ledger_count},
                "totals": {"gross_emissions_g": to_float(q_g(sum((j.emissions_g for j in eng.jobs.values()), ZERO))),
                           "energy_kwh": to_float(sum((j.energy_kwh for j in eng.jobs.values()), ZERO)),
                           "deadline_misses": sum(1 for j in eng.jobs.values() if j.deadline_missed)},
                "jobs": {"total": len(eng.jobs), **counts},
                "controller": {"policy": cfg.policy, "policy_label": POLICIES[cfg.policy].label,
                               "state": clock.controller_state, "band": band,
                               "inversion_active": eng.effective_debt() > ZERO and POLICIES[cfg.policy].debt_aware,
                               "throttle": {k: to_float(v) for k, v in THROTTLE_TABLE[band].items()}},
                "recent_decisions": [self.decision_dict(d, clock) for d in recent],
                "mode": self.mode,
            }

    def timeline(self) -> dict[str, Any]:
        with self.db.session() as s:
            clock = self.clock(s)
            rows = s.scalars(select(TimelineRow).order_by(TimelineRow.slot)).all()
            return {"points": [{
                "slot": r.slot, "sim_time": self._time(clock, r.slot), "intensity": to_float(r.intensity),
                "source": r.intensity_source, "green": r.green, "balance_g": to_float(r.balance_g),
                "accrued_g": to_float(r.accrued_g), "effective_debt_g": to_float(r.effective_debt_g),
                "cum_emissions_g": to_float(r.cum_emissions_g), "cum_debt_g": to_float(r.cum_debt_g),
                "cum_credit_g": to_float(r.cum_credit_g), "band": r.band, "controller_state": r.controller_state,
                "running": r.running, "paused": r.paused, "queued": r.queued, "deferred": r.deferred,
                "completed": r.completed, "throttled": r.throttled} for r in rows]}

    def carbon_curve(self) -> dict[str, Any]:
        with self.db.session() as s:
            cfg = self.config(s)
            clock = self.clock(s)
            curve = self.curve(s, cfg)
            lo, hi = self.curve_window(clock, len(curve))
            return {
                "provider": curve.provider, "region": curve.region, "profile": cfg.profile,
                "profile_description": PROFILE_DESCRIPTIONS.get(cfg.profile),
                "green_threshold": to_float(cfg.green_threshold), "debt_threshold": to_float(cfg.debt_intensity_threshold),
                "current_slot": clock.current_slot, "slot_minutes": float(self.slot_minutes),
                "points": [{"slot": i, "sim_time": self._time(clock, i), "intensity": to_float(curve.at(i)),
                            "source": curve.source_at(i)} for i in range(lo, hi)],
            }

    def gantt(self) -> dict[str, Any]:
        with self.db.session() as s:
            clock = self.clock(s)
            jobs = s.scalars(select(JobRow).order_by(JobRow.arrival_slot, JobRow.id)).all()
            execs = s.scalars(select(ExecutionRow).order_by(ExecutionRow.slot)).all()
            by_job: dict[str, list[dict[str, Any]]] = {}
            for e in execs:
                by_job.setdefault(e.job_id, []).append({"slot": e.slot, "capacity": to_float(e.capacity),
                                                        "intensity": to_float(e.intensity)})
            return {"current_slot": clock.current_slot, "jobs": [{
                "id": j.id, "name": j.name, "job_class": j.job_class, "state": j.state,
                "arrival_slot": j.arrival_slot, "deadline_slot": j.deadline_slot, "start_slot": j.start_slot,
                "finish_slot": j.finish_slot, "planned_start_slot": j.planned_start_slot,
                "deferred_by_controller": j.deferred_by_controller, "segments": by_job.get(j.id, [])} for j in jobs]}

    def controller_view(self) -> dict[str, Any]:
        with self.db.session() as s:
            eng, clock, cfg = self.build_engine(s)
            plan = build_plan(eng, eng.now)  # read-only projection for the current slot
            repay = [self.job_summary(r, clock) for r in s.scalars(
                select(JobRow).where(JobRow.deferred_by_controller.is_(True)).order_by(JobRow.planned_start_slot)).all()]
            throttled = [self.job_summary(r, clock) for r in s.scalars(
                select(JobRow).where(JobRow.state.in_([JobState.RUNNING, JobState.PAUSED]))).all()]
            debt = eng.effective_debt()
            return {
                "settings": cfg.model_dump(mode="json"),
                "policies": [{"name": p.name, "label": p.label, "uses_forecast": p.uses_forecast,
                              "debt_aware": p.debt_aware} for p in POLICIES.values()],
                "profiles": PROFILE_DESCRIPTIONS,
                "state": clock.controller_state, "band": clock.band, "band_names": BAND_STATES,
                "throttle_table": {str(b): {k: to_float(v) for k, v in row.items()} for b, row in THROTTLE_TABLE.items()},
                "effective_debt_g": to_float(debt), "balance_g": to_float(eng.ledger.balance_g),
                "current_intensity": to_float(eng.intensity(eng.now)), "green_now": eng.is_green(eng.now),
                "plan": self.plan_dict(eng, plan),
                "plan_is_advisory": cfg.policy != "debt_predictive",
                "repayment_queue": [j for j in repay if j["state"] not in ("completed", "failed", "cancelled")],
                "repaid_jobs": [j for j in repay if j["state"] == "completed"],
                "active_jobs": throttled,
            }

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self.lock, self.db.session() as s:
            current = self.config(s).model_dump(mode="json")
            if "override" in patch and isinstance(patch["override"], dict):
                patch = {**patch, "override": {**current["override"], **patch["override"]}}
            merged = {**current, **patch}
            cfg = ControllerConfig.model_validate(merged)
            if cfg.carbon_source == "live_snapshot":
                has_snap = s.scalars(select(ProviderSnapshotRow).limit(1)).first() is not None
                if not has_snap:
                    raise Conflict("capture a live provider snapshot before switching carbon_source to live_snapshot")
            self.save_config(s, cfg)
            changed = sorted(k for k in patch if current.get(k) != merged.get(k))
            if changed:
                eng_clock = self.clock(s)
                s.add(DecisionRow(slot=eng_clock.current_slot, job_id=None, action="SETTINGS_CHANGED",
                                  reason="Controller settings changed: " + ", ".join(changed) +
                                         ". New values apply from the next tick.",
                                  policy=cfg.policy, controller_state=eng_clock.controller_state,
                                  intensity=Decimal("0"), details={k: merged[k] for k in changed}))
            return cfg.model_dump(mode="json")

    def workload_stats(self) -> list[dict[str, Any]]:
        with self.db.session() as s:
            rows = s.scalars(select(JobRow)).all()
        groups: dict[str, list[JobRow]] = {}
        for r in rows:
            groups.setdefault(r.workload, []).append(r)
        out = []
        for name, jobs in sorted(groups.items()):
            debt = q_g(sum((j.debt_g for j in jobs), ZERO))
            credit = q_g(sum((j.credit_g for j in jobs), ZERO))
            completed = [j for j in jobs if j.state == JobState.COMPLETED and j.finish_slot is not None]
            delays = [float((j.finish_slot - j.arrival_slot) * self.slot_minutes - j.runtime_min) for j in completed]
            out.append({
                "workload": name, "jobs": len(jobs), "completed": len(completed),
                "emissions_g": to_float(q_g(sum((j.emissions_g for j in jobs), ZERO))),
                "debt_g": to_float(debt), "credit_g": to_float(credit),
                "credit_earned_g": to_float(q_g(sum((j.credit_earned_g for j in jobs), ZERO))),
                "net_g": to_float(q_g(debt - credit)),
                "deadline_misses": sum(1 for j in jobs if j.deadline_missed),
                "deferrals": sum(j.deferral_count for j in jobs),
                "avg_delay_min": round(sum(delays) / len(delays), 1) if delays else None,
            })
        return out

    def scenario_status(self) -> dict[str, Any]:
        with self.db.session() as s:
            clock = self.clock(s)
            cfg = self.config(s)
            thr = cfg.debt_intensity_threshold
            emerg_ids = set(s.scalars(select(JobRow.id).where(JobRow.job_class == "emergency")).all())
            first_exec = None
            for e in s.scalars(select(ExecutionRow).order_by(ExecutionRow.slot)).all():
                if e.job_id in emerg_ids and e.intensity > thr:
                    first_exec = e
                    break
            debt = s.scalars(select(LedgerRow).where(LedgerRow.event_type == EventType.DEBT_INCURRED)
                             .order_by(LedgerRow.seq).limit(1)).first()
            after = first_exec.slot if first_exec else 0
            intervention = s.scalars(select(DecisionRow).where(DecisionRow.action.in_(
                ["DEFER", "THROTTLE", "PAUSE"]), DecisionRow.slot >= after).order_by(DecisionRow.id).limit(1)).first()
            green = None
            if debt is not None:
                green = s.scalars(select(TimelineRow).where(TimelineRow.green.is_(True), TimelineRow.slot >= after)
                                  .order_by(TimelineRow.slot).limit(1)).first()
            repay = s.scalars(select(DecisionRow).where(DecisionRow.action == "REPAYMENT_START")
                              .order_by(DecisionRow.id).limit(1)).first()
            credit = s.scalars(select(LedgerRow).where(LedgerRow.event_type == EventType.CREDIT_VERIFIED)
                               .order_by(LedgerRow.seq)).all()
            applied = [c for c in credit if c.amount_g < ZERO]
            # Prefer the first credit earned in a green window (the repayment the scenario demonstrates).
            credit_applied = next((c for c in applied if c.intensity_actual is not None
                                   and c.intensity_actual <= cfg.green_threshold), applied[0] if applied else None)
            cleared = s.scalars(select(LedgerRow).where(LedgerRow.event_type == EventType.DEBT_CLEARED)
                                .order_by(LedgerRow.seq).limit(1)).first()
            last = s.scalars(select(LedgerRow).order_by(LedgerRow.seq.desc()).limit(1)).first()
            t = lambda slot: self._time(clock, slot)  # noqa: E731

            def ledger_time(row: LedgerRow | None) -> str | None:
                return row.sim_time if row else None

            steps = [
                {"key": "emergency", "title": "High-carbon emergency execution", "done": first_exec is not None,
                 "time": t(first_exec.slot) if first_exec else None,
                 "detail": f"{first_exec.job_id} ran at {first_exec.intensity} gCO₂e/kWh (> {thr})" if first_exec else None},
                {"key": "debt", "title": "Carbon debt created", "done": debt is not None, "time": ledger_time(debt),
                 "detail": f"{debt.event_id}: +{debt.amount_g} g booked when {debt.job_id} completed" if debt else None},
                {"key": "intervention", "title": "Controller intervention", "done": intervention is not None,
                 "time": t(intervention.slot) if intervention else None,
                 "detail": f"{intervention.action} {intervention.job_id}: {intervention.reason[:140]}" if intervention else None},
                {"key": "green", "title": "Green window available", "done": green is not None,
                 "time": t(green.slot) if green else None,
                 "detail": f"Intensity {green.intensity} ≤ {cfg.green_threshold} gCO₂e/kWh" if green else None},
                {"key": "repayment", "title": "Repayment job execution", "done": repay is not None,
                 "time": t(repay.slot) if repay else None,
                 "detail": f"{repay.job_id} started as repayment work" if repay else None},
                {"key": "credit", "title": "Verified credit created", "done": credit_applied is not None,
                 "time": ledger_time(credit_applied),
                 "detail": (f"{credit_applied.event_id}: {credit_applied.amount_g} g for {credit_applied.job_id} "
                            f"(baseline {credit_applied.intensity_baseline} → actual {credit_applied.intensity_actual})")
                 if credit_applied else None},
                {"key": "balance", "title": "Outstanding debt updated", "done": cleared is not None,
                 "time": ledger_time(cleared) or ledger_time(last),
                 "detail": ("Debt repaid to zero — priority inversion lifted" if cleared else
                            (f"Outstanding balance {last.balance_after_g} g" if last else None))},
            ]
            return {"active": clock.scenario_active, "autoplay": clock.autoplay, "slot": clock.current_slot,
                    "sim_time": t(clock.current_slot), "start_slot": SCENARIO_START_SLOT,
                    "end_slot": SCENARIO_END_SLOT, "steps": steps,
                    "complete": all(st["done"] for st in steps),
                    "demo_jobs": [{"name": d.name, "class": d.job_class, "story": d.story} for d in DEMO_JOBS]}

    # ----------------------------------------------------------- mode hooks
    def validate_job_times(self, data: dict[str, Any]) -> None:
        """Simulation jobs are scheduled in 15-minute slots."""
        for key in ("runtime_min", "deadline_offset_min", "arrival_offset_min"):
            value = data.get(key) or 0
            if int(value) % 15:
                raise InvalidInput(f"{key} must be a multiple of 15 minutes in Simulation mode")

    def horizon_slot(self, clock: SimClockRow) -> int:
        return HORIZON_SLOTS

    def curve_window(self, clock: SimClockRow, length: int) -> tuple[int, int]:
        """Slots returned for charts: the whole simulated horizon."""
        return 0, min(length, HORIZON_SLOTS + 1)

    def epoch(self) -> datetime:
        with self.db.session() as s:
            return self.clock(s).epoch
