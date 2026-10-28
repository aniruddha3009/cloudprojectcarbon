"""Discrete-time scheduling engine (15-minute slots).

One call to :meth:`Engine.step` processes slot ``t``:

  1. arrivals            pending jobs whose arrival slot has come become QUEUED
  2. operator actions    held jobs are released, operator "run now" requests start
  3. policy decision     the active policy starts / defers / throttles / waits
  4. execution           every running job does one slot of work; energy,
                         emissions and debt are computed per slot (Decimal)
  5. settlement          finished jobs book DEBT / CREDIT ledger events
  6. deadline checks     unfinished jobs past their deadline are flagged
  7. snapshot            a timeline point is recorded for charts/metrics

The engine is pure and deterministic: no database, no wall clock (a clock
function is injected), no randomness. The service layer rebuilds an engine
from the database for each tick and persists the new records afterwards.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Callable

from . import accounting as acc
from .carbon_curve import SLOT_MINUTES, CarbonCurve
from .config_model import ControllerConfig
from .ledger import EventType, LedgerBook
from .units import ONE, ZERO, D, q_g, q_intensity

if TYPE_CHECKING:  # pragma: no cover
    from .policies import Policy
    from .planner import Plan

DEFAULT_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)


class JobState:
    PENDING = "pending"
    QUEUED = "queued"
    DEFERRED = "deferred"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATES = {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    JobState.PENDING: {JobState.QUEUED, JobState.CANCELLED},
    JobState.QUEUED: {JobState.RUNNING, JobState.DEFERRED, JobState.CANCELLED},
    JobState.DEFERRED: {JobState.RUNNING, JobState.DEFERRED, JobState.QUEUED, JobState.CANCELLED},
    JobState.RUNNING: {JobState.PAUSED, JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED},
    JobState.PAUSED: {JobState.RUNNING, JobState.FAILED, JobState.CANCELLED},
    JobState.COMPLETED: set(),
    JobState.FAILED: set(),
    JobState.CANCELLED: set(),
}

JOB_CLASSES = ("emergency", "normal", "background")


class InvalidTransition(ValueError):
    pass


def slots_needed(remaining_min: Decimal, capacity: Decimal, slot_minutes: Decimal | int = SLOT_MINUTES) -> int:
    """Whole slots needed to finish ``remaining_min`` of full-speed work at ``capacity``."""
    if remaining_min <= ZERO:
        return 0
    if capacity <= ZERO:
        return 10**9
    return math.ceil(remaining_min / (D(slot_minutes) * capacity))


@dataclass
class SimJob:
    id: str
    name: str
    workload: str
    job_class: str
    priority: int
    power_w: Decimal
    runtime_min: int
    arrival_slot: int
    deadline_slot: int
    max_wait_min: int | None = None
    simulate_failure: bool = False
    state: str = JobState.PENDING
    capacity: Decimal = ONE
    work_done_min: Decimal = ZERO
    start_slot: int | None = None
    finish_slot: int | None = None
    energy_kwh: Decimal = ZERO
    emissions_g: Decimal = ZERO
    debt_g: Decimal = ZERO
    credit_g: Decimal = ZERO
    credit_earned_g: Decimal = ZERO
    deferred_by_controller: bool = False
    deferral_event_id: str | None = None
    baseline_intensity: Decimal | None = None
    baseline_slot: int | None = None
    planned_start_slot: int | None = None
    hold_until_slot: int | None = None
    manual_run: bool = False
    credit_void_reason: str | None = None
    deadline_missed: bool = False
    forced: bool = False
    deferral_count: int = 0
    throttle_count: int = 0
    last_decision_key: str | None = None
    last_reason: str | None = None
    debt_booked: bool = False
    credit_settled: bool = False
    ledger_event_ids: list[str] = field(default_factory=list)
    # Accounting slot length this job is scheduled in (15 min in simulation, 30 s in live mode).
    slot_minutes: Decimal = D(SLOT_MINUTES)

    @property
    def is_emergency(self) -> bool:
        return self.job_class == "emergency"

    @property
    def remaining_min(self) -> Decimal:
        return max(ZERO, D(self.runtime_min) - self.work_done_min)

    @property
    def energy_full_kwh(self) -> Decimal:
        """Counterfactual energy: the whole job at full speed (estimated)."""
        return acc.energy_kwh(self.power_w, self.runtime_min)

    @property
    def avg_intensity(self) -> Decimal | None:
        if self.energy_kwh <= ZERO:
            return None
        return q_intensity(self.emissions_g / self.energy_kwh)

    def latest_start(self) -> int:
        return self.deadline_slot - slots_needed(self.remaining_min, ONE, self.slot_minutes)


@dataclass
class Decision:
    slot: int
    job_id: str | None
    action: str
    reason: str
    policy: str
    controller_state: str
    intensity: Decimal
    capacity: Decimal | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class Segment:
    job_id: str
    slot: int
    capacity: Decimal
    power_w: Decimal
    minutes: Decimal
    energy_kwh: Decimal
    intensity: Decimal
    intensity_source: str
    emissions_g: Decimal
    debt_g: Decimal
    kernel: dict[str, Any] | None = None
    energy_source: str = "ESTIMATED_MODEL"


@dataclass
class TimelinePoint:
    slot: int
    intensity: Decimal
    intensity_source: str
    green: bool
    balance_g: Decimal
    accrued_g: Decimal
    effective_debt_g: Decimal
    cum_emissions_g: Decimal
    cum_debt_g: Decimal
    cum_credit_g: Decimal
    band: int
    controller_state: str
    running: int
    paused: int
    queued: int
    deferred: int
    completed: int
    throttled: int


KernelFn = Callable[[SimJob, Decimal], dict[str, Any]]
# Live mode supplies measured energy: (job, capacity, minutes) -> (avg power W, energy kWh, evidence).
EnergyFn = Callable[[SimJob, Decimal, Decimal], tuple[Decimal, Decimal, dict[str, Any]]]

ENERGY_LABELS = {
    "ESTIMATED_MODEL": "ESTIMATED (declared power × runtime model)",
    "MEASURED_RAPL_ATTRIBUTED": "MEASURED CPU-package energy (Windows Energy Meter / RAPL), attributed to the job by its CPU-time share",
    "ESTIMATED_CPU_TIME": "ESTIMATED (measured CPU time × assumed watts per busy core)",
}


class Engine:
    def __init__(
        self,
        config: ControllerConfig,
        curve: CarbonCurve,
        jobs: list[SimJob],
        policy: "Policy",
        ledger: LedgerBook | None = None,
        now: int = 0,
        epoch: datetime = DEFAULT_EPOCH,
        wall_clock: Callable[[], datetime] | None = None,
        kernel: KernelFn | None = None,
        controller_state: str = "NORMAL",
        slot_minutes: Decimal | int = SLOT_MINUTES,
        energy_fn: EnergyFn | None = None,
    ) -> None:
        self.slot_minutes = D(slot_minutes)
        self.energy_fn = energy_fn
        # Human-readable energy source written into ledger entries and receipts.
        self.energy_label = ENERGY_LABELS["ESTIMATED_MODEL"]
        self.config = config
        self.curve = curve
        self.jobs: dict[str, SimJob] = {j.id: j for j in jobs}
        self.policy = policy
        self.ledger = ledger or LedgerBook()
        self.now = now
        self.epoch = epoch
        self.wall_clock = wall_clock
        self.kernel = kernel
        self.controller_state = controller_state
        self.band_value = 0
        self.last_plan: "Plan | None" = None
        self.new_decisions: list[Decision] = []
        self.new_segments: list[Segment] = []
        self.new_timeline: list[TimelinePoint] = []
        self.decision_ns_total = 0
        self.decision_calls = 0

    # ------------------------------------------------------------------ time
    def slot_time(self, slot: int) -> datetime:
        return self.epoch + timedelta(minutes=float(self.slot_minutes) * slot)

    def iso(self, slot: int) -> str:
        return self.slot_time(slot).strftime("%Y-%m-%dT%H:%M:%SZ")

    def hhmm(self, slot: int) -> str:
        if self.slot_minutes != SLOT_MINUTES:  # live mode: real clock time
            return self.slot_time(slot).strftime("%H:%M:%S UTC")
        day, rem = divmod(slot * SLOT_MINUTES, 24 * 60)
        label = f"{rem // 60:02d}:{rem % 60:02d}"
        return label if day == 0 else f"D+{day} {label}"

    def _recorded_at(self, slot: int) -> str:
        if self.wall_clock is not None:
            return self.wall_clock().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        return self.iso(slot)

    # --------------------------------------------------------------- queries
    def intensity(self, slot: int) -> Decimal:
        return self.curve.at(slot)

    def is_green(self, slot: int) -> bool:
        return self.curve.at(slot) <= self.config.green_threshold

    def jobs_in(self, *states: str) -> list[SimJob]:
        return sorted((j for j in self.jobs.values() if j.state in states), key=lambda j: j.id)

    def active_jobs(self) -> list[SimJob]:
        return self.jobs_in(JobState.RUNNING, JobState.PAUSED)

    def ready_jobs(self, emergency: bool) -> list[SimJob]:
        return [
            j for j in self.jobs_in(JobState.QUEUED, JobState.DEFERRED)
            if j.is_emergency == emergency and j.hold_until_slot is None and not j.manual_run
        ]

    def _active_usage(self) -> tuple[Decimal, Decimal]:
        """Capacity in use (worker units). A job at 50% uses 0.5 of a worker; a paused job uses none."""
        e = f = ZERO
        for j in self.active_jobs():
            if j.is_emergency:
                e += j.capacity
            else:
                f += j.capacity
        return e, f

    def total_free(self) -> Decimal:
        e, f = self._active_usage()
        return D(self.config.workers) - e - f

    def flex_free(self) -> Decimal:
        """Capacity available to flexible work; ``emergency_reserve`` workers are kept for emergencies."""
        e, f = self._active_usage()
        return D(self.config.workers) - max(D(self.config.emergency_reserve), e) - f

    def accrued_debt(self) -> Decimal:
        return q_g(sum((j.debt_g for j in self.active_jobs() if not j.debt_booked), ZERO))

    def effective_debt(self) -> Decimal:
        """Booked ledger balance + debt accrued by jobs still running."""
        return q_g(self.ledger.balance_g + self.accrued_debt())

    def band(self, debt: Decimal) -> int:
        c = self.config
        if debt <= ZERO:
            return 0
        if debt < c.debt_soft_g:
            return 1
        if debt < c.debt_hard_g:
            return 2
        if debt < c.debt_critical_g:
            return 3
        return 4

    def starving(self, job: SimJob, t: int) -> bool:
        return job.max_wait_min is not None and (t - job.arrival_slot) * self.slot_minutes >= job.max_wait_min

    # ------------------------------------------------------------- logging
    def log(
        self,
        job: SimJob | None,
        action: str,
        reason: str,
        *,
        dedupe: str | None = None,
        capacity: Decimal | None = None,
        details: dict[str, Any] | None = None,
    ) -> bool:
        if job is not None and dedupe is not None:
            key = f"{action}|{dedupe}"
            if job.last_decision_key == key:
                return False
            job.last_decision_key = key
        elif job is not None:
            job.last_decision_key = f"{action}|"
        if job is not None:
            job.last_reason = reason
        self.new_decisions.append(
            Decision(
                slot=self.now,
                job_id=job.id if job else None,
                action=action,
                reason=reason,
                policy=self.policy.name,
                controller_state=self.controller_state,
                intensity=self.intensity(self.now),
                capacity=capacity,
                details=details or {},
            )
        )
        return True

    # ---------------------------------------------------------- transitions
    @staticmethod
    def transition(job: SimJob, new_state: str) -> None:
        if new_state not in ALLOWED_TRANSITIONS.get(job.state, set()):
            raise InvalidTransition(f"{job.id}: {job.state} → {new_state} is not allowed")
        job.state = new_state

    def start(self, job: SimJob, capacity: Decimal, action: str, reason: str, details: dict[str, Any] | None = None) -> None:
        self.transition(job, JobState.RUNNING)
        job.capacity = capacity
        job.start_slot = self.now if job.start_slot is None else job.start_slot
        job.planned_start_slot = None
        job.forced = action == "START_FORCED"
        self.log(job, action, reason, capacity=capacity, details=details)

    def defer(self, job: SimJob, until_slot: int, reason: str, details: dict[str, Any] | None = None) -> None:
        """Deliberate controller deferral of a job that *could* run now.

        The first deferral records the counterfactual baseline (forecast average
        intensity had the job started now) as a hash-chained DEFERRAL_RECORDED
        event — the reference any later credit must cite.
        """
        t = self.now
        if not job.deferred_by_controller:
            need = slots_needed(job.remaining_min, ONE, job.slot_minutes)
            baseline = self.curve.window_avg(t, need)
            rec = self.ledger.append(
                event_type=EventType.DEFERRAL_RECORDED,
                idem_key=f"DEFERRAL:{job.id}",
                sim_time=self.iso(t),
                recorded_at=self._recorded_at(t),
                job_id=job.id,
                energy_kwh=job.energy_full_kwh,
                intensity_baseline=baseline,
                details={
                    "policy": self.policy.name,
                    "baseline_window": f"{self.hhmm(t)}–{self.hhmm(t + need)}",
                    "baseline_source": self.curve.source_at(t),
                    "counterfactual_emissions_g": str(acc.gross_emissions_g(job.energy_full_kwh, baseline)),
                    "planned_start": self.iso(until_slot),
                    "deadline": self.iso(job.deadline_slot),
                    "reason": reason,
                },
            )
            job.deferred_by_controller = True
            job.deferral_event_id = rec.event_id
            job.baseline_intensity = baseline
            job.baseline_slot = t
            job.ledger_event_ids.append(rec.event_id)
        if job.state == JobState.QUEUED:
            self.transition(job, JobState.DEFERRED)
        job.planned_start_slot = until_slot
        if self.log(job, "DEFER", reason, dedupe=str(until_slot), details=details):
            job.deferral_count += 1

    def wait(self, job: SimJob, reason: str, planned_start: int | None = None) -> None:
        job.planned_start_slot = planned_start
        self.log(job, "WAIT_CAPACITY", reason, dedupe=str(planned_start))

    def set_capacity(self, job: SimJob, capacity: Decimal, reason: str) -> None:
        if capacity == job.capacity and not (job.state == JobState.PAUSED and capacity > ZERO):
            return
        old = job.capacity
        if capacity <= ZERO:
            self.transition(job, JobState.PAUSED)
            action = "PAUSE"
        else:
            if job.state == JobState.PAUSED:
                self.transition(job, JobState.RUNNING)
            action = "THROTTLE" if capacity < old else "RESTORE"
        job.capacity = capacity
        if action in ("THROTTLE", "PAUSE"):
            job.throttle_count += 1
        self.log(job, action, reason, capacity=capacity, details={"from": str(old), "to": str(capacity)})

    # ------------------------------------------------------ operator actions
    def operator_cancel(self, job: SimJob, reason: str = "Cancelled by operator") -> None:
        if job.state in TERMINAL_STATES:
            raise InvalidTransition(f"{job.id} is already {job.state}")
        if job.state in (JobState.RUNNING, JobState.PAUSED):
            self._close(job, self.now, JobState.CANCELLED, reason)
        else:
            self.transition(job, JobState.CANCELLED)
            job.finish_slot = self.now
            self.log(job, "CANCELLED", reason)
            self._settle(job)

    def operator_hold(self, job: SimJob, until_slot: int) -> None:
        if job.state not in (JobState.QUEUED, JobState.DEFERRED, JobState.PENDING):
            raise InvalidTransition(f"{job.id}: only waiting jobs can be held (state {job.state})")
        if until_slot <= self.now:
            raise ValueError("hold must end in the future")
        if job.state == JobState.PENDING:
            raise InvalidTransition(f"{job.id} has not arrived yet")
        if job.state == JobState.QUEUED:
            self.transition(job, JobState.DEFERRED)
        job.hold_until_slot = until_slot
        job.planned_start_slot = until_slot
        self.log(job, "OPERATOR_HOLD",
                 f"Operator deferred the job until {self.hhmm(until_slot)}. Operator deferrals are not controller "
                 f"decisions and do not create a credit baseline.")

    def operator_run(self, job: SimJob) -> None:
        if job.state not in (JobState.QUEUED, JobState.DEFERRED):
            raise InvalidTransition(f"{job.id}: only queued or deferred jobs can be run now (state {job.state})")
        job.manual_run = True
        job.hold_until_slot = None

    # ------------------------------------------------------------- the step
    def step(self) -> None:
        """Simulation: decide and execute slot ``now`` instantly."""
        self.begin_slot()
        self.finish_slot()

    def begin_slot(self) -> None:
        """Decision phase for slot ``now`` (arrivals, operator requests, policy decision).

        Live mode calls this at the start of a real time slot, lets the work happen, and calls
        :meth:`finish_slot` when the slot has elapsed, so energy can be measured.
        """
        t = self.now
        self._arrivals(t)
        self._operator_queue(t)
        started = time.perf_counter_ns()
        self.policy.decide(self, t)
        self.decision_ns_total += time.perf_counter_ns() - started
        self.decision_calls += 1

    def finish_slot(self) -> None:
        """Accounting phase for slot ``now``: energy, emissions, debt, settlement, snapshot."""
        t = self.now
        self._execute(t)
        self._deadline_checks(t)
        self._snapshot(t)
        self.now = t + 1

    def run_until(self, end_slot: int) -> None:
        while self.now < end_slot:
            self.step()

    def all_settled(self) -> bool:
        return all(j.state in TERMINAL_STATES for j in self.jobs.values())

    def _arrivals(self, t: int) -> None:
        for job in self.jobs_in(JobState.PENDING):
            if job.arrival_slot <= t:
                self.transition(job, JobState.QUEUED)
                self.log(job, "ARRIVED",
                         f"{job.job_class.capitalize()} job arrived (priority {job.priority}, "
                         f"{job.runtime_min} min at {job.power_w} W, deadline {self.hhmm(job.deadline_slot)}).")

    def _operator_queue(self, t: int) -> None:
        for job in self.jobs_in(JobState.DEFERRED):
            if job.hold_until_slot is not None and job.hold_until_slot <= t:
                job.hold_until_slot = None
                self.log(job, "HOLD_RELEASED", "Operator hold expired; job returns to the controller.")
        for job in self.jobs_in(JobState.QUEUED, JobState.DEFERRED):
            if not job.manual_run:
                continue
            if self.total_free() >= 1:
                job.manual_run = False
                if job.deferred_by_controller:
                    job.credit_void_reason = "operator override started the job outside the controller's plan"
                self.start(job, ONE, "MANUAL_START",
                           "Operator override: started immediately at full capacity. Any repayment credit is voided "
                           "because the controller no longer chose the execution window.")
            else:
                self.wait(job, "Operator requested immediate run, but all workers are busy.")

    def _execute(self, t: int) -> None:
        cfg = self.config
        intensity = self.intensity(t)
        source = self.curve.source_at(t)
        for job in self.jobs_in(JobState.RUNNING):
            c = job.capacity
            if c <= ZERO:
                continue
            remaining = job.remaining_min
            slot_work = self.slot_minutes * c
            if remaining <= slot_work:
                work, minutes = remaining, remaining / c
            else:
                work, minutes = slot_work, self.slot_minutes
            if self.energy_fn is not None:
                power, energy, kernel = self.energy_fn(job, c, minutes)
                energy_source = str(kernel.get("energy_source", "ESTIMATED_CPU_TIME"))
            else:
                power = acc.throttled_power_w(job.power_w, c, cfg.static_power_fraction)
                energy = acc.energy_kwh(power, minutes)
                kernel = self.kernel(job, c) if self.kernel else None
                energy_source = "ESTIMATED_MODEL"
            emissions = acc.gross_emissions_g(energy, intensity)
            debt = acc.debt_g(energy, intensity, cfg.debt_intensity_threshold)
            job.work_done_min += work
            job.energy_kwh += energy
            job.emissions_g += emissions
            job.debt_g += debt
            self.new_segments.append(Segment(job.id, t, c, power, minutes, energy, intensity, source, emissions, debt,
                                             kernel, energy_source))
            if job.simulate_failure and job.work_done_min * 2 >= D(job.runtime_min) and job.remaining_min > ZERO:
                self._close(job, t + 1, JobState.FAILED, "Simulated worker failure at 50% progress (fault-injection flag).")
            elif job.remaining_min <= ZERO:
                self._close(job, t + 1, JobState.COMPLETED, "Job finished.")

    def _close(self, job: SimJob, end_slot: int, outcome: str, reason: str) -> None:
        self.transition(job, outcome)
        job.finish_slot = end_slot
        if outcome == JobState.COMPLETED and end_slot > job.deadline_slot:
            job.deadline_missed = True
        action = {"completed": "COMPLETED", "failed": "FAILED", "cancelled": "CANCELLED"}[outcome]
        summary = (f"{reason} Energy {job.energy_kwh} kWh, emissions {job.emissions_g} g, "
                   f"debt {job.debt_g} g; deadline {'missed' if job.deadline_missed else 'met'}.")
        self.log(job, action, summary)
        self._settle(job)

    def _settle(self, job: SimJob) -> None:
        """Book this job's ledger events exactly once (idempotency keys enforce it)."""
        t_end = job.finish_slot if job.finish_slot is not None else self.now
        sim_time, rec_at = self.iso(t_end), self._recorded_at(t_end)
        if job.debt_g > ZERO and not job.debt_booked:
            rec = self.ledger.append(
                event_type=EventType.DEBT_INCURRED,
                idem_key=f"DEBT:{job.id}",
                sim_time=sim_time,
                recorded_at=rec_at,
                job_id=job.id,
                amount_g=job.debt_g,
                energy_kwh=job.energy_kwh,
                intensity_actual=job.avg_intensity,
                details={
                    "job_class": job.job_class,
                    "outcome": job.state,
                    "gross_emissions_g": str(job.emissions_g),
                    "debt_intensity_threshold": str(self.config.debt_intensity_threshold),
                    "execution_window": f"{self.hhmm(job.start_slot or t_end)}–{self.hhmm(t_end)}",
                    "cause": "emergency execution during high-carbon period" if job.is_emergency
                    else ("deadline-forced execution above threshold" if job.forced
                          else "execution above the debt intensity threshold"),
                    "energy_source": self.energy_label,
                },
            )
            job.debt_booked = True
            job.ledger_event_ids.append(rec.event_id)
        if job.deferred_by_controller and not job.credit_settled:
            decision = acc.evaluate_credit(
                deferred_by_controller=job.deferred_by_controller,
                deferral_event_id=job.deferral_event_id,
                baseline_intensity=job.baseline_intensity,
                completed=job.state == JobState.COMPLETED,
                finished_slot=job.finish_slot,
                deadline_slot=job.deadline_slot,
                already_credited=f"CREDIT:{job.id}" in self.ledger.idem_keys,
                void_reason=job.credit_void_reason,
                counterfactual_energy_kwh=job.energy_full_kwh,
                actual_emissions_g=job.emissions_g,
            )
            common = {
                "checks": {k: v for k, v in decision.checks.items()},
                "reasons": decision.reasons,
                "counterfactual_energy_kwh": str(job.energy_full_kwh),
                "counterfactual_emissions_g": str(acc.gross_emissions_g(job.energy_full_kwh, job.baseline_intensity or ZERO)),
                "actual_emissions_g": str(job.emissions_g),
                "energy_source": self.energy_label,
            }
            if decision.eligible:
                before = self.ledger.balance_g
                applied = min(decision.credit_g, before)
                rec = self.ledger.append(
                    event_type=EventType.CREDIT_VERIFIED,
                    idem_key=f"CREDIT:{job.id}",
                    sim_time=sim_time,
                    recorded_at=rec_at,
                    job_id=job.id,
                    amount_g=-applied,
                    energy_kwh=job.energy_kwh,
                    intensity_actual=job.avg_intensity,
                    intensity_baseline=job.baseline_intensity,
                    reference_event_id=job.deferral_event_id,
                    details={
                        **common,
                        "credit_earned_g": str(decision.credit_g),
                        "credit_applied_g": str(q_g(applied)),
                        "surplus_not_banked_g": str(q_g(decision.credit_g - applied)),
                    },
                )
                job.credit_earned_g = decision.credit_g
                job.credit_g = q_g(applied)
                job.ledger_event_ids.append(rec.event_id)
                if before > ZERO and self.ledger.balance_g == ZERO:
                    cleared = self.ledger.append(
                        event_type=EventType.DEBT_CLEARED,
                        idem_key=f"CLEARED:{rec.seq}",
                        sim_time=sim_time,
                        recorded_at=rec_at,
                        job_id=job.id,
                        reference_event_id=rec.event_id,
                        details={"message": "Outstanding carbon debt repaid to zero; priority inversion lifted."},
                    )
                    job.ledger_event_ids.append(cleared.event_id)
                    self.log(None, "DEBT_CLEARED",
                             f"Credit from {job.id} repaid the outstanding debt to zero; priority inversion lifted.")
            else:
                rec = self.ledger.append(
                    event_type=EventType.CREDIT_DENIED,
                    idem_key=f"CREDIT:{job.id}",
                    sim_time=sim_time,
                    recorded_at=rec_at,
                    job_id=job.id,
                    intensity_actual=job.avg_intensity,
                    intensity_baseline=job.baseline_intensity,
                    reference_event_id=job.deferral_event_id,
                    details=common,
                )
                job.ledger_event_ids.append(rec.event_id)
            job.credit_settled = True

    def _deadline_checks(self, t: int) -> None:
        for job in self.jobs.values():
            if job.state not in TERMINAL_STATES and job.state != JobState.PENDING and not job.deadline_missed \
                    and t + 1 > job.deadline_slot:
                job.deadline_missed = True
                self.log(job, "DEADLINE_MISSED",
                         f"Deadline {self.hhmm(job.deadline_slot)} passed before completion; job continues best-effort "
                         f"and is no longer credit-eligible.")

    def _snapshot(self, t: int) -> None:
        jobs = list(self.jobs.values())
        accrued = self.accrued_debt()
        self.new_timeline.append(
            TimelinePoint(
                slot=t,
                intensity=self.intensity(t),
                intensity_source=self.curve.source_at(t),
                green=self.is_green(t),
                balance_g=self.ledger.balance_g,
                accrued_g=accrued,
                effective_debt_g=q_g(self.ledger.balance_g + accrued),
                cum_emissions_g=q_g(sum((j.emissions_g for j in jobs), ZERO)),
                cum_debt_g=self.ledger.total_debt_g,
                cum_credit_g=self.ledger.total_credit_applied_g,
                band=self.band_value,
                controller_state=self.controller_state,
                running=sum(1 for j in jobs if j.state == JobState.RUNNING),
                paused=sum(1 for j in jobs if j.state == JobState.PAUSED),
                queued=sum(1 for j in jobs if j.state == JobState.QUEUED),
                deferred=sum(1 for j in jobs if j.state == JobState.DEFERRED),
                completed=sum(1 for j in jobs if j.state == JobState.COMPLETED),
                throttled=sum(1 for j in jobs if j.state in (JobState.RUNNING, JobState.PAUSED) and j.capacity < ONE),
            )
        )
