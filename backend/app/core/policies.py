"""Scheduling policies compared in the experiments.

  fifo             Ordinary priority scheduling; carbon-unaware (baseline 1).
  threshold        Defer flexible work while intensity > I_threshold (baseline 2).
  debt_reactive    Carbon debt controller without forecasting: priority
                   inversion to green slots while debt > 0, progressive
                   throttling by debt band; looks only at the current slot.
  debt_predictive  Full controller: debt controller + capacity-aware forecast
                   planner + debt projection + proactive throttling.

All policies share emergency precedence, deadline-safety checks and the same
accounting, so differences in results come from the decisions alone.
"""

from __future__ import annotations

from decimal import Decimal

from .engine import ONE, ZERO, Engine, SimJob, slots_needed
from .planner import URGENT_SLACK_SLOTS, build_plan, credit_potential
from .units import q_g

CAPACITY_LEVELS = [Decimal("0"), Decimal("0.2"), Decimal("0.5"), Decimal("1")]

# Desired capacity per debt band and workload class, applied outside green slots.
THROTTLE_TABLE: dict[int, dict[str, Decimal]] = {
    0: {"normal": Decimal("1"), "background": Decimal("1")},
    1: {"normal": Decimal("1"), "background": Decimal("1")},
    2: {"normal": Decimal("1"), "background": Decimal("0.5")},
    3: {"normal": Decimal("0.5"), "background": Decimal("0.2")},
    4: {"normal": Decimal("0.2"), "background": Decimal("0")},
}
BAND_STATES = {0: "NORMAL", 1: "REPAYING", 2: "THROTTLE_SOFT", 3: "THROTTLE_HARD", 4: "CRITICAL"}


def fmt_g(value: Decimal) -> str:
    return f"{q_g(value).normalize():f}" if value != ZERO else "0"


def fmt_i(value: Decimal) -> str:
    return f"{value:.0f}"


def feasible_at(job: SimJob, start: int, capacity: Decimal = ONE) -> bool:
    return start + slots_needed(job.remaining_min, capacity, job.slot_minutes) <= job.deadline_slot


THROTTLE_MARGIN_SLOTS = 2


def min_feasible_capacity(job: SimJob, t: int, desired: Decimal, margin: int = THROTTLE_MARGIN_SLOTS) -> Decimal:
    """Smallest capacity level ≥ desired that still meets the deadline with a safety margin.

    Throttling must leave ``margin`` slots of slack before the deadline so a job is never
    slowed right up to the edge (where any capacity contention would cause a miss).
    Pausing (0) is allowed only if the job can still finish at full speed when resumed
    next slot. If nothing is feasible the job runs at full capacity.
    """
    for level in CAPACITY_LEVELS:
        if level < desired:
            continue
        if level == ONE:
            return ONE
        start = t + 1 if level == ZERO else t
        need = slots_needed(job.remaining_min, ONE if level == ZERO else level, job.slot_minutes)
        if start + need + margin <= job.deadline_slot:
            return level
    return ONE


def admit_emergencies(eng: Engine, t: int) -> None:
    thr = eng.config.debt_intensity_threshold
    for job in sorted(eng.ready_jobs(emergency=True), key=lambda j: (j.priority, j.arrival_slot, j.id)):
        if eng.total_free() >= 1:
            intensity = eng.intensity(t)
            reason = f"Emergency precedence: started immediately at {fmt_i(intensity)} gCO₂e/kWh"
            reason += (f"; energy above the {fmt_i(thr)} gCO₂e/kWh threshold is booked as carbon debt."
                       if intensity > thr else "; intensity is below the debt threshold so no debt accrues.")
            eng.start(job, ONE, "EMERGENCY_START", reason)
        else:
            eng.wait(job, "All workers are busy; emergency job is first in line (cluster is non-preemptive).")


def update_controller_state(eng: Engine, band: int, debt: Decimal, note: str = "") -> None:
    state = BAND_STATES[band]
    eng.band_value = band
    if state != eng.controller_state:
        cfg = eng.config
        table = THROTTLE_TABLE[band]
        msg = (f"Effective debt {fmt_g(debt)} g → {state}. Outside green windows: normal "
               f"{int(table['normal'] * 100)}%, background {int(table['background'] * 100)}% capacity "
               f"(bands: soft {fmt_g(cfg.debt_soft_g)} / hard {fmt_g(cfg.debt_hard_g)} / critical {fmt_g(cfg.debt_critical_g)} g).")
        if band > 0:
            msg += " Priority inversion active: flexible work is steered into green slots until debt returns to zero."
        eng.controller_state = state
        eng.log(None, "CONTROLLER_STATE", msg + note, details={"band": band, "debt_g": str(debt)})


def apply_throttle(eng: Engine, t: int, band: int, green: bool) -> None:
    for job in eng.active_jobs():
        if job.is_emergency:
            continue  # emergencies are never carbon-throttled
        desired = ONE if green else THROTTLE_TABLE[band][job.job_class]
        level = min_feasible_capacity(job, t, desired)
        capacity_limited = False
        if level > job.capacity:
            # Growing back needs free capacity: other jobs may have used the share this job released.
            headroom = job.capacity + max(eng.flex_free(), ZERO)
            if level > headroom:
                level = max((lv for lv in CAPACITY_LEVELS if lv <= headroom), default=ZERO)
                capacity_limited = True
        if level == job.capacity and not (level > ZERO and job.state == "paused"):
            continue
        if capacity_limited:
            reason = (f"Wanted {int(desired * 100)}% but only {int(level * 100)}% of a worker is free; "
                      f"capacity-limited restore (deadline {eng.hhmm(job.deadline_slot)} may be at risk).")
        elif green:
            reason = "Green slot: throttle lifted, full capacity restored."
        elif level > desired:
            reason = (f"Debt band {BAND_STATES[band]} asks for {int(desired * 100)}% but the deadline "
                      f"{eng.hhmm(job.deadline_slot)} needs at least {int(level * 100)}% — deadline-safe throttle.")
        elif level == ZERO:
            reason = (f"Debt band {BAND_STATES[band]} at {fmt_i(eng.intensity(t))} gCO₂e/kWh: background job paused "
                      f"(checkpointed); deadline {eng.hhmm(job.deadline_slot)} remains feasible.")
        elif level < ONE:
            reason = (f"Debt band {BAND_STATES[band]} at {fmt_i(eng.intensity(t))} gCO₂e/kWh: scheduler capacity "
                      f"limited to {int(level * 100)}%; deadline {eng.hhmm(job.deadline_slot)} remains feasible. "
                      f"Note: throttling raises energy per unit of work (static power).")
        else:
            reason = "Debt band no longer requires throttling; full capacity restored."
        eng.set_capacity(job, level, reason)


class Policy:
    name = "base"
    label = "Base"
    uses_forecast = False
    debt_aware = False

    def decide(self, eng: Engine, t: int) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class FifoPolicy(Policy):
    name = "fifo"
    label = "FIFO / priority (carbon-unaware)"

    def decide(self, eng: Engine, t: int) -> None:
        eng.controller_state = "CARBON_UNAWARE"
        admit_emergencies(eng, t)
        for job in sorted(eng.ready_jobs(emergency=False), key=lambda j: (j.priority, j.arrival_slot, j.id)):
            if eng.flex_free() >= 1:
                eng.start(job, ONE, "START", "FIFO/priority order: started as soon as a worker was free; "
                                              "carbon intensity is not considered.")
            else:
                eng.wait(job, "Waiting for a free worker (FIFO/priority order).")


class ThresholdPolicy(Policy):
    name = "threshold"
    label = "Threshold-only carbon-aware deferral"

    def decide(self, eng: Engine, t: int) -> None:
        eng.controller_state = "THRESHOLD"
        admit_emergencies(eng, t)
        thr = eng.config.debt_intensity_threshold
        intensity = eng.intensity(t)
        for job in sorted(eng.ready_jobs(emergency=False), key=lambda j: (j.priority, j.arrival_slot, j.id)):
            if eng.flex_free() < 1:
                eng.wait(job, "Waiting for a free worker.")
            elif eng.starving(job, t):
                eng.start(job, ONE, "START_FORCED", f"Maximum wait of {job.max_wait_min} min reached (starvation guard).")
            elif intensity <= thr:
                eng.start(job, ONE, "START", f"Intensity {fmt_i(intensity)} ≤ threshold {fmt_i(thr)} gCO₂e/kWh.")
            elif feasible_at(job, t + 1):
                eng.defer(job, t + 1,
                          f"Intensity {fmt_i(intensity)} > threshold {fmt_i(thr)} gCO₂e/kWh; deadline "
                          f"{eng.hhmm(job.deadline_slot)} still feasible, re-evaluate next slot.")
            else:
                eng.start(job, ONE, "START_FORCED",
                          f"Deadline-forced: waiting any longer would miss {eng.hhmm(job.deadline_slot)}; "
                          f"runs at {fmt_i(intensity)} gCO₂e/kWh.")


class DebtReactivePolicy(Policy):
    name = "debt_reactive"
    label = "Carbon debt controller (no forecast)"
    debt_aware = True

    def decide(self, eng: Engine, t: int) -> None:
        cfg = eng.config
        debt = eng.effective_debt()
        band = eng.band(debt)
        intensity = eng.intensity(t)
        green = intensity <= cfg.green_threshold
        update_controller_state(eng, band, debt)
        admit_emergencies(eng, t)
        apply_throttle(eng, t, band, green)

        def order(j: SimJob) -> tuple:
            urgent = j.latest_start() - t <= URGENT_SLACK_SLOTS
            value = -credit_potential(eng, j, t) if debt > ZERO else Decimal(j.priority)
            return (0 if urgent else 1, value, j.deadline_slot, j.id)

        for job in sorted(eng.ready_jobs(emergency=False), key=order):
            if eng.flex_free() < 1:
                eng.wait(job, "Waiting for a free worker.")
                continue
            if eng.starving(job, t):
                eng.start(job, ONE, "START_FORCED", f"Maximum wait of {job.max_wait_min} min reached (starvation guard).")
                continue
            can_wait = feasible_at(job, t + 1)
            if debt > ZERO:
                if green:
                    action = "REPAYMENT_START" if job.deferred_by_controller else "START"
                    eng.start(job, ONE, action,
                              f"Green slot ({fmt_i(intensity)} ≤ {fmt_i(cfg.green_threshold)} gCO₂e/kWh) with "
                              f"{fmt_g(debt)} g debt outstanding: runs as repayment work; priority inversion ranks "
                              f"waiting jobs by repayment value, not nominal priority.")
                elif can_wait:
                    eng.defer(job, t + 1,
                              f"{fmt_g(debt)} g carbon debt outstanding: priority inversion restricts flexible work "
                              f"to green slots (≤ {fmt_i(cfg.green_threshold)}). No forecast — re-check next slot. "
                              f"Deadline {eng.hhmm(job.deadline_slot)} still feasible.")
                else:
                    eng.start(job, ONE, "START_FORCED",
                              f"Deadline-forced: no time left to wait for a green slot before "
                              f"{eng.hhmm(job.deadline_slot)}; runs at {fmt_i(intensity)} gCO₂e/kWh.")
            else:
                thr = cfg.debt_intensity_threshold
                if intensity <= thr:
                    eng.start(job, ONE, "START", f"No debt and intensity {fmt_i(intensity)} ≤ {fmt_i(thr)} gCO₂e/kWh.")
                elif can_wait:
                    eng.defer(job, t + 1,
                              f"Intensity {fmt_i(intensity)} > threshold {fmt_i(thr)} gCO₂e/kWh; deadline still "
                              f"feasible, re-evaluate next slot.")
                else:
                    eng.start(job, ONE, "START_FORCED",
                              f"Deadline-forced at {fmt_i(intensity)} gCO₂e/kWh to meet {eng.hhmm(job.deadline_slot)}.")


class DebtPredictivePolicy(Policy):
    name = "debt_predictive"
    label = "Predictive carbon debt controller (full)"
    uses_forecast = True
    debt_aware = True

    def decide(self, eng: Engine, t: int) -> None:
        cfg = eng.config
        debt = eng.effective_debt()
        band = eng.band(debt)
        intensity = eng.intensity(t)
        green = intensity <= cfg.green_threshold
        admit_emergencies(eng, t)  # before planning, so the plan sees the capacity they take
        plan = build_plan(eng, t)
        eng.last_plan = plan

        effective_band = band
        note = ""
        if cfg.proactive_throttling and band > 0 and band < 4 and (
            plan.end_balance_g > ZERO or plan.peak_g >= cfg.debt_critical_g
        ):
            effective_band = band + 1
            note = (f" Proactive: projection shows {fmt_g(plan.end_balance_g)} g still outstanding at the planning "
                    f"horizon (peak {fmt_g(plan.peak_g)} g), so throttling is raised one band early.")
        update_controller_state(eng, effective_band, debt, note)
        apply_throttle(eng, t, effective_band, green)

        def issue_order(p) -> tuple:
            # Jobs starting now are dispatched by repayment value while debt is outstanding (priority inversion).
            value = -credit_potential(eng, p.job, t) if debt > ZERO else Decimal(p.job.priority)
            return (0 if p.start == t else 1, value, p.job.id)

        for p in sorted(plan.placements, key=issue_order):
            job = p.job
            if p.start == t:
                if eng.flex_free() < 1:
                    eng.wait(job, "Planned to start now but no worker is free.", t + 1)
                    continue
                if p.forced:
                    action = "START_FORCED"
                elif job.deferred_by_controller and green and debt > ZERO:
                    action = "REPAYMENT_START"
                else:
                    action = "START"
                eng.start(job, ONE, action, p.reason, details=p.details())
            elif p.start is None:
                eng.wait(job, p.reason)
            elif p.deliberate or job.deferred_by_controller:
                eng.defer(job, p.start, p.reason, details=p.details())
            else:
                eng.wait(job, p.reason, p.start)


POLICIES: dict[str, type[Policy]] = {
    p.name: p for p in (FifoPolicy, ThresholdPolicy, DebtReactivePolicy, DebtPredictivePolicy)
}


def make_policy(name: str) -> Policy:
    try:
        return POLICIES[name]()
    except KeyError as exc:
        raise ValueError(f"unknown policy {name}") from exc
