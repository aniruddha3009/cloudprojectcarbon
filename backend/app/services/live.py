"""Live mode: real grid readings, real laptop telemetry, real (bounded) managed workloads.

How a live accounting slot works (default 30 s, LIVE_SLOT_SECONDS):
  1. begin   The engine makes its normal policy decision for the slot using the latest real grid
             reading (India Energy Atlas). Running jobs get a CPU worker thread at their capacity.
  2. work    Each managed job burns a *bounded* amount of real CPU (at most LIVE_JOB_DUTY of one core
             at 100 % capacity) for the length of the slot. Ordinary Windows programs are only watched.
  3. finish  When the slot ends, each job's energy is measured: CPU-package energy for the slot (Windows
             Energy Meter / RAPL) × the job's share of all busy CPU time. If no meter exists, energy is
             estimated as CPU-seconds × LIVE_CORE_WATTS and labelled ESTIMATED. Emissions, debt, credits
             and ledger entries then use exactly the same code as Simulation mode.

Nothing in this module invents grid data. If no real reading has ever been received, live scheduling
waits and the dashboard says why.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..core.carbon_curve import CarbonCurve
from ..core.config_model import ControllerConfig
from ..core.engine import ENERGY_LABELS, TERMINAL_STATES, Engine, JobState, SimJob
from ..core.units import D, q_kwh, q_w
from ..db import Database
from ..models import (CarbonReadingRow, DecisionRow, ExecutionRow, GridReadingRow, JobRow, LedgerRow, SettingRow,
                      SimClockRow, TimelineRow, utcnow)
from .india_energy_atlas import PROVIDER, IndiaEnergyAtlas, ProviderError
from .simulation import InvalidInput, SimulationService
from .system_monitor import SystemMonitor

log = logging.getLogger("carbon_debt.live")

FORECAST_AHEAD_SLOTS = 720
UNAVAILABLE = "UNAVAILABLE"
RETRY_SECONDS = 120  # retry delay after a timeout / server error (each retry counts toward the daily quota)

LIVE_DEMO_JOBS = [
    # name, workload, class, priority, runtime_min, deadline_offset_min
    ("Hospital model failover", "triage-ai", "emergency", 1, 2, 4),
    ("Billing report", "billing", "normal", 2, 3, 8),
    ("Nightly ETL backfill", "data-platform", "normal", 3, 2, 20),
    ("Search index rebuild", "search", "background", 4, 4, 30),
]


class _Worker(threading.Thread):
    """A bounded CPU workload: hashes data for ``duty × capacity`` of every 100 ms, then sleeps."""

    def __init__(self, job_id: str, duty: float) -> None:
        super().__init__(name=f"live-job-{job_id}", daemon=True)
        self.duty = duty
        self.capacity = 0.0
        self.cpu_s = 0.0
        self._taken = 0.0
        self._lock = threading.Lock()
        self._stop_evt = threading.Event()
        self._buf = hashlib.sha256(job_id.encode()).digest() * 2048  # 64 KiB; hashlib releases the GIL

    def run(self) -> None:
        while not self._stop_evt.is_set():
            busy = 0.1 * self.duty * self.capacity
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < busy:
                hashlib.sha256(self._buf).digest()
            with self._lock:
                self.cpu_s = time.thread_time()
            self._stop_evt.wait(max(0.0, 0.1 - (time.perf_counter() - t0)))

    def take_cpu(self) -> float:
        with self._lock:
            delta, self._taken = self.cpu_s - self._taken, self.cpu_s
            return max(0.0, delta)

    def stop(self) -> None:
        self._stop_evt.set()


class WorkerPool:
    def __init__(self, duty: float) -> None:
        self.duty = duty
        self._workers: dict[str, _Worker] = {}

    def set(self, job_id: str, capacity: float) -> None:
        w = self._workers.get(job_id)
        if w is None:
            w = self._workers[job_id] = _Worker(job_id, self.duty)
            w.start()
        w.capacity = capacity

    def take_cpu(self, job_id: str) -> float:
        w = self._workers.get(job_id)
        return w.take_cpu() if w else 0.0

    def stop(self, job_id: str) -> None:
        w = self._workers.pop(job_id, None)
        if w:
            w.stop()

    def stop_all(self) -> None:
        for job_id in list(self._workers):
            self.stop(job_id)

    def running(self) -> dict[str, float]:
        return {k: w.capacity for k, w in self._workers.items()}


class GridFeed:
    """Polls India Energy Atlas at a quota-safe interval and stores every reading."""

    def __init__(self, db: Database, settings: Settings, provider: IndiaEnergyAtlas | None = None) -> None:
        self.db = db
        self.settings = settings
        self.provider = provider or IndiaEnergyAtlas(settings)
        self.poll_s = settings.india_energy_atlas_poll_minutes * 60
        self.forecast_s = settings.india_energy_atlas_forecast_hours * 3600
        self.last_attempt: datetime | None = None
        self.last_success: datetime | None = None
        self.last_forecast: datetime | None = None
        self.last_error: dict[str, Any] | None = None
        self.calls_today = 0
        self._day = datetime.now(timezone.utc).date()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="grid-feed", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _count_call(self) -> bool:
        today = datetime.now(timezone.utc).date()
        if today != self._day:
            self._day, self.calls_today = today, 0
        if self.calls_today >= 95:  # free keys allow 100 calls/day; keep a margin
            self.last_error = {"code": "daily_budget", "message": "Daily API budget used up (95 of 100 calls); polling resumes tomorrow."}
            return False
        self.calls_today += 1
        return True

    def next_interval_s(self) -> float:
        """Normal quota-safe interval; a network or server failure is retried after 2 minutes instead."""
        code = (self.last_error or {}).get("code", "")
        transient = code == "unreachable" or code.startswith("http_5")
        return min(self.poll_s, RETRY_SECONDS) if transient else self.poll_s

    def _run(self) -> None:
        while not self._stop.is_set():
            now = datetime.now(timezone.utc)
            if self.last_attempt is None or (now - self.last_attempt).total_seconds() >= self.next_interval_s():
                self.fetch_latest()
            if self.provider.configured and self.last_success and (
                    self.last_forecast is None or (now - self.last_forecast).total_seconds() >= self.forecast_s):
                self.fetch_forecast()
            self._stop.wait(5)

    def fetch_latest(self) -> bool:
        with self._lock:
            self.last_attempt = datetime.now(timezone.utc)
            if not self.provider.configured:
                self.last_error = {"code": "missing_api_key", "message": "No API key configured. Set INDIA_ENERGY_ATLAS_API_KEY "
                                   "(in .env locally, or in the cloud service's environment settings), then restart the backend."}
                return False
            if not self._count_call():
                return False
            try:
                r = self.provider.latest()
            except ProviderError as exc:
                self.last_error = {"code": exc.code, "message": str(exc), "status": exc.status}
                log.warning("grid feed error", extra={"code": exc.code})
                return False
            with self.db.session() as s:
                exists = s.scalars(select(GridReadingRow).where(GridReadingRow.kind == "actual",
                                                                GridReadingRow.as_of == r.as_of)).first()
                if exists is None:
                    s.add(GridReadingRow(kind="actual", as_of=r.as_of, intensity=r.intensity, scope=r.scope,
                                         provider=PROVIDER, dominant_fuel=r.dominant_fuel, fetched_at=r.fetched_at))
            self.last_success, self.last_error = r.fetched_at, None
            return True

    def fetch_forecast(self) -> bool:
        with self._lock:
            if not self._count_call():
                return False
            try:
                points = self.provider.forecast(24)
            except ProviderError as exc:
                # The forecast is optional; the controller falls back to "latest reading persists".
                self.last_forecast = datetime.now(timezone.utc)
                self.last_error = {"code": exc.code, "message": f"Forecast: {exc}", "status": exc.status}
                return False
            with self.db.session() as s:
                s.execute(delete(GridReadingRow).where(GridReadingRow.kind == "forecast"))
                for p in points:
                    if p.is_forecast:
                        s.add(GridReadingRow(kind="forecast", as_of=p.timestamp, intensity=p.intensity,
                                             scope=self.provider.region, provider=PROVIDER))
            self.last_forecast = datetime.now(timezone.utc)
            return True

    def latest_row(self) -> GridReadingRow | None:
        with self.db.session() as s:
            return s.scalars(select(GridReadingRow).where(GridReadingRow.kind == "actual")
                             .order_by(GridReadingRow.as_of.desc()).limit(1)).first()

    def status(self) -> dict[str, Any]:
        latest = self.latest_row()
        now = datetime.now(timezone.utc)
        as_of = latest.as_of.replace(tzinfo=latest.as_of.tzinfo or timezone.utc) if latest else None
        if not self.provider.configured:
            state = "not_configured"
        elif self.last_error and (not self.last_success or (self.last_attempt and self.last_attempt > self.last_success)):
            state = "error"
        elif latest is None:
            state = "waiting"
        else:
            age = (now - as_of).total_seconds()
            state = "ok" if age <= 3 * 3600 else "stale"
        fmt = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ") if d else None  # noqa: E731
        next_poll = self.last_attempt + timedelta(seconds=self.next_interval_s()) if self.last_attempt else None
        with self.db.session() as s:
            forecast_points = s.scalar(select(func.count()).select_from(GridReadingRow).where(GridReadingRow.kind == "forecast")) or 0
        return {
            "provider": PROVIDER, "region": self.provider.region, "configured": self.provider.configured,
            "state": state, "polling": self.running,
            "intensity": float(latest.intensity) if latest else None,
            "dominant_fuel": latest.dominant_fuel if latest else None,
            "reading_time": fmt(as_of), "last_success": fmt(self.last_success), "last_attempt": fmt(self.last_attempt),
            "age_seconds": round((now - as_of).total_seconds()) if as_of else None,
            "next_poll": fmt(next_poll), "poll_minutes": self.settings.india_energy_atlas_poll_minutes,
            "calls_today": self.calls_today, "forecast_points": forecast_points,
            "rate_limit": self.provider.rate_limit, "error": self.last_error,
            "notes": "The provider models India's fuel mix from SLDC/IEX/POSOCO data (±3 % national, ±6 % state).",
        }


class LiveService(SimulationService):
    mode = "live"

    def __init__(self, db: Database, settings: Settings, monitor: SystemMonitor, feed: GridFeed) -> None:
        super().__init__(db, settings)
        self.slot_seconds = settings.live_slot_seconds
        self.slot_minutes = D(settings.live_slot_seconds) / D(60)
        self.monitor = monitor
        self.feed = feed
        self.workers = WorkerPool(settings.live_job_duty)
        self._window = None

    # ------------------------------------------------------------ clock/curve
    def clock(self, s: Session) -> SimClockRow:
        clock = s.get(SimClockRow, 1)
        if clock is None:
            clock = SimClockRow(id=1, epoch=datetime.now(timezone.utc).replace(microsecond=0), current_slot=0,
                                autoplay=False, speed_ms=self.slot_seconds * 1000)
            s.add(clock)
            s.flush()
        if clock.epoch.tzinfo is None:
            clock.epoch = clock.epoch.replace(tzinfo=timezone.utc)
        return clock

    def horizon_slot(self, clock: SimClockRow) -> int:
        return 10**9

    def curve_window(self, clock: SimClockRow, length: int) -> tuple[int, int]:
        """Charts show the last hour of real readings and the next 30 minutes of forecast."""
        back = int(3600 // self.slot_seconds)
        ahead = int(1800 // self.slot_seconds)
        return max(0, clock.current_slot - back), min(length, clock.current_slot + ahead)

    def _slot_start(self, clock: SimClockRow, slot: int) -> datetime:
        return clock.epoch + timedelta(seconds=self.slot_seconds * slot)

    def curve(self, s: Session, cfg: ControllerConfig) -> CarbonCurve:
        """Past/current slots: the latest real reading at that time. Future slots: the provider forecast
        for that hour if available, otherwise the latest reading persists (labelled PERSISTENCE)."""
        clock = self.clock(s)
        actual = s.scalars(select(GridReadingRow).where(GridReadingRow.kind == "actual").order_by(GridReadingRow.as_of)).all()
        if not actual:
            return CarbonCurve([Decimal(0)], [UNAVAILABLE], provider=PROVIDER, region=self.feed.provider.region)
        forecast = s.scalars(select(GridReadingRow).where(GridReadingRow.kind == "forecast").order_by(GridReadingRow.as_of)).all()
        tz = lambda d: d if d.tzinfo else d.replace(tzinfo=timezone.utc)  # noqa: E731
        actual_t = [(tz(r.as_of), r.intensity) for r in actual]
        forecast_t = [(tz(r.as_of), r.intensity) for r in forecast]
        now = datetime.now(timezone.utc)
        values: list[Decimal] = []
        sources: list[str] = []
        last_actual = actual_t[-1][1]
        for slot in range(clock.current_slot + FORECAST_AHEAD_SLOTS):
            ts = self._slot_start(clock, slot)
            if ts <= now:
                past = [v for t, v in actual_t if t <= ts]
                values.append(past[-1] if past else actual_t[0][1])
                sources.append("LIVE_ACTUAL")
            else:
                hour = [v for t, v in forecast_t if t <= ts < t + timedelta(hours=1)]
                if hour:
                    values.append(hour[0])
                    sources.append("LIVE_FORECAST")
                else:
                    values.append(last_actual)
                    sources.append("PERSISTENCE")
        return CarbonCurve(values, sources, provider=PROVIDER, region=self.feed.provider.region)

    # ----------------------------------------------------------------- energy
    def engine_options(self, with_kernel: bool) -> dict[str, Any]:
        return {"energy_fn": self._measured_energy}

    def build_engine(self, s: Session, with_kernel: bool = False):
        eng, clock, cfg = super().build_engine(s, with_kernel)
        eng.energy_label = ENERGY_LABELS["MEASURED_RAPL_ATTRIBUTED" if self.monitor.meter.available else "ESTIMATED_CPU_TIME"]
        return eng, clock, cfg

    def _measured_energy(self, job: SimJob, capacity: Decimal, minutes: Decimal) -> tuple[Decimal, Decimal, dict[str, Any]]:
        cpu_s = self.workers.take_cpu(job.id)
        w = self._window
        if self.monitor.meter.available and w is not None and w.package_j > 0:
            share = min(1.0, cpu_s / max(w.busy_cpu_s, cpu_s, 1e-9))
            joules = w.package_j * share
            source = "MEASURED_RAPL_ATTRIBUTED"
            info = {"package_energy_j": round(w.package_j, 3), "all_busy_cpu_s": round(w.busy_cpu_s, 3), "cpu_share": round(share, 4)}
        else:
            joules = cpu_s * self.settings.live_core_watts
            source = "ESTIMATED_CPU_TIME"
            info = {"assumed_watts_per_busy_core": self.settings.live_core_watts}
        energy_kwh = q_kwh(D(round(joules, 6)) / D(3_600_000))
        power_w = q_w(D(round(joules / self.slot_seconds, 6)))
        info.update({"energy_source": source, "cpu_ms": round(cpu_s * 1000, 3), "energy_j": round(joules, 4),
                     "wall_ms": float(minutes) * 60_000})
        return power_w, energy_kwh, info

    def persist(self, s: Session, eng: Engine, clock: SimClockRow) -> None:
        # Store the worker CPU time in the execution-attempt columns as well.
        for seg in eng.new_segments:
            if seg.kernel:
                seg.kernel.setdefault("iterations", None)
        super().persist(s, eng, clock)

    # ------------------------------------------------------------ live loop
    def grid_available(self, s: Session) -> bool:
        return s.scalars(select(GridReadingRow.id).where(GridReadingRow.kind == "actual").limit(1)).first() is not None

    def _open_slot(self, s: Session) -> int | None:
        row = s.get(SettingRow, "live_open_slot")
        return None if row is None or row.value is None else int(row.value)

    def _sync_workers(self, eng: Engine) -> None:
        for job in eng.jobs.values():
            if job.state == JobState.RUNNING and job.capacity > 0:
                self.workers.set(job.id, float(job.capacity))
            elif job.state == JobState.PAUSED:
                self.workers.set(job.id, 0.0)
            else:
                self.workers.stop(job.id)

    def live_tick(self, force: bool = False) -> dict[str, Any]:
        """Close the slot in progress (measured accounting) and open the next one."""
        with self.lock, self.db.session() as s:
            clock = self.clock(s)
            if not self.grid_available(s):
                return {"advanced": False, "reason": "no real grid reading yet"}
            due = int((datetime.now(timezone.utc) - clock.epoch).total_seconds() // self.slot_seconds)
            open_slot = self._open_slot(s)
            if open_slot is not None and due <= open_slot and not force:
                return {"advanced": False, "reason": "slot in progress"}
            self._window = self.monitor.consume_window()
            eng, clock, _ = self.build_engine(s)
            if open_slot is not None and open_slot == eng.now:
                eng.finish_slot()
            if due > eng.now:  # monitoring was paused: skip the slots nobody ran (no work, no energy)
                eng.now = due
            eng.begin_slot()
            self._sync_workers(eng)
            self.persist(s, eng, clock)
            self._save_setting(s, "live_open_slot", eng.now)
            return {"advanced": True, "slot": eng.now}

    def _autoplay_loop(self) -> None:
        while not self._stop.is_set():
            try:
                with self.db.session() as s:
                    monitoring = self.clock(s).autoplay
                if monitoring:
                    self.live_tick()
            except Exception:
                log.exception("live tick failed")
            self._stop.wait(1.0)

    def set_autoplay(self, enabled: bool, speed_ms: int | None = None) -> dict[str, Any]:
        """Start or stop Live monitoring (process telemetry, grid feed and managed workloads)."""
        with self.lock, self.db.session() as s:
            clock = self.clock(s)
            clock.autoplay = enabled
        if enabled:
            self.monitor.start()
            self.feed.start()
            self.live_tick(force=False)
        else:
            self.stop_monitoring()
        return {"autoplay": enabled, "monitoring": enabled, "speed_ms": self.slot_seconds * 1000}

    def stop_monitoring(self) -> None:
        with self.lock, self.db.session() as s:
            clock = self.clock(s)
            clock.autoplay = False
            # Close the slot in progress so the CPU work already done is accounted, not lost.
            if self._open_slot(s) == clock.current_slot and self.grid_available(s):
                self._window = self.monitor.consume_window()
                eng, clock, _ = self.build_engine(s)
                eng.finish_slot()
                self.persist(s, eng, clock)
            self._save_setting(s, "live_open_slot", None)
        self.workers.stop_all()
        self.monitor.stop()
        self.feed.stop()

    def create_job(self, data: dict[str, Any]) -> dict[str, Any]:
        # While no slot is open (monitoring off, or no grid reading yet) the live clock is idle; move it to the
        # current real time so the job's arrival and deadline are measured from *now*.
        with self.lock, self.db.session() as s:
            clock = self.clock(s)
            due = int((datetime.now(timezone.utc) - clock.epoch).total_seconds() // self.slot_seconds)
            if self._open_slot(s) is None and clock.current_slot < due:
                clock.current_slot = due
        return super().create_job(data)

    def stop_background(self) -> None:
        super().stop_background()
        self.stop_monitoring()

    # -------------------------------------------------------- mode overrides
    def tick(self, slots: int = 1) -> dict[str, Any]:
        raise InvalidInput("Live mode follows real time. Use Start monitoring instead of Step.")

    def run_scenario(self, mode: str, speed_ms: int | None = None) -> dict[str, Any]:
        raise InvalidInput("The emergency-to-green scenario is a controlled demonstration: switch to Simulation mode.")

    def set_grid(self, preset: str, intensity: Decimal | None, hours: float) -> dict[str, Any]:
        raise InvalidInput("Live mode uses the real India Energy Atlas reading; the grid can only be set in Simulation mode.")

    def load_samples(self) -> list[str]:
        return self.load_demo()

    def slot_label(self, slot: int | None) -> str | None:
        return None  # live times are shown by the browser in local time, not inside the sentence

    def validate_job_times(self, data: dict[str, Any]) -> None:
        if not 1 <= int(data["runtime_min"]) <= 10:
            raise InvalidInput("Live workloads must run 1–10 minutes so they stay small and finish normally.")
        if int(data.get("arrival_offset_min") or 0) != 0:
            raise InvalidInput("Live workloads arrive immediately (arrival_offset_min must be 0).")
        if int(data["deadline_offset_min"]) > 240:
            raise InvalidInput("Live deadlines must be within 4 hours.")
        data["power_w"] = Decimal(str(round(self.settings.live_core_watts * self.settings.live_job_duty, 3)))

    def load_demo(self) -> list[str]:
        ids = []
        for name, workload, cls, prio, runtime, deadline in LIVE_DEMO_JOBS:
            res = self.create_job({"name": name, "workload": workload, "job_class": cls, "priority": prio,
                                   "runtime_min": runtime, "deadline_offset_min": deadline, "arrival_offset_min": 0})
            ids.append(res["job"]["id"])
        return ids

    def reset(self, slot: int = 0) -> None:
        self.workers.stop_all()
        with self.lock, self.db.session() as s:
            for model in (ExecutionRow, DecisionRow, LedgerRow, TimelineRow, CarbonReadingRow, JobRow):
                s.execute(delete(model))
            s.execute(delete(SettingRow).where(SettingRow.key.in_(["last_plan", "live_open_slot"])))
            clock = self.clock(s)
            clock.epoch = datetime.now(timezone.utc).replace(microsecond=0)
            clock.current_slot = 0
            clock.controller_state = "NORMAL"
            clock.band = 0
            clock.next_job_number = 1
            clock.run_id += 1
            monitoring = clock.autoplay
        if monitoring:
            self.live_tick(force=True)

    # ----------------------------------------------------------------- views
    def state(self) -> dict[str, Any]:
        data = super().state()
        with self.db.session() as s:
            available = self.grid_available(s)
        if not available:
            data["carbon"].update({"intensity": None, "green": False, "source": UNAVAILABLE})
        data["carbon"]["mode"] = "LIVE"
        data["live"] = {"monitoring": data["clock"]["autoplay"], "grid": self.feed.status(),
                        "energy_meter": self.monitor.snapshot()["energy_meter"],
                        "system": self.monitor.snapshot().get("system"), "slot_seconds": self.slot_seconds,
                        "workers": self.workers.running()}
        return data

    def controller_view(self) -> dict[str, Any]:
        data = super().controller_view()
        with self.db.session() as s:
            if not self.grid_available(s):
                data["plan"].update({"placements": [], "projection": [],
                                     "uncertainty_note": "No real grid reading yet, so no plan can be made."})
                data["current_intensity"] = None
        return data

    def carbon_curve(self) -> dict[str, Any]:
        data = super().carbon_curve()
        if data["points"] and data["points"][0]["source"] == UNAVAILABLE:
            data["points"] = []
        return data

    def live_status(self) -> dict[str, Any]:
        # Watching processes is read-only, so it runs whenever Live mode is viewed, not only while monitoring.
        self.monitor.start()
        with self.db.session() as s:
            clock = self.clock(s)
            monitoring = clock.autoplay
            managed = [self.job_summary(r, clock) for r in s.scalars(select(JobRow).order_by(JobRow.id)).all()]
            cpu: dict[str, float] = {}
            for row in s.scalars(select(ExecutionRow)).all():
                cpu[row.job_id] = cpu.get(row.job_id, 0.0) + (row.kernel_cpu_ms or 0.0)
        for job in managed:
            job["cpu_ms_total"] = round(cpu.get(job["id"], 0.0), 1)
            job["worker_active"] = job["id"] in self.workers.running()
        return {"monitoring": monitoring, "telemetry": self.monitor.snapshot(), "grid": self.feed.status(),
                "managed_workloads": [j for j in managed if j["state"] not in TERMINAL_STATES] + [j for j in managed if j["state"] in TERMINAL_STATES][:10],
                "slot_seconds": self.slot_seconds}
