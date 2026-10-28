"""Predictive debt planner (rule-based; no machine learning).

Each slot the planner builds a capacity-aware reservation plan over the
forecast horizon:

  1. A free-capacity table is built for slots t … H for flexible work
     (workers − emergency reserve − jobs already running, assuming each runs at
     its current capacity until it finishes).
  2. Waiting flexible jobs reserve capacity earliest-deadline-first (EDF protects
     feasibility); ties are broken by repayment value while debt is outstanding
     (priority inversion) or by nominal priority otherwise. Windows keep a
     safety margin of up to 2 slots before the deadline when slack allows.
  3. For each job every start slot s with s + runtime ≤ deadline and free
     capacity is scored by the forecast mean intensity of its run window.
     With debt outstanding only fully-green windows are allowed if any exist
     (strict green-slot repayment); otherwise the least-carbon feasible window
     is used (deadline protection). The earliest window within 10 gCO2e/kWh of
     the best is chosen, and the capacity is reserved.
  4. When no debt is outstanding the job is only delayed if the expected
     saving ≥ min_deferral_savings_g (avoids pointless delay).
  4b. Repair: if some job has no feasible window, earlier-deadline jobs that
     were being delayed are pinned to their earliest feasible start and the
     plan is rebuilt (at most 3 passes) — greedy carbon placement must not
     starve a later job of capacity.
  5. A debt projection walks the plan forward: expected debt from runs above
     I_threshold, expected credits from deferred jobs (capped at the balance —
     no banking). Peak and end-of-horizon balance drive proactive throttling.

Forecast uncertainty is NOT modelled: the forecast is the (simulated or
captured) curve itself. This is stated in the UI and the documentation.
Complexity per slot: O(J · W · R) for J jobs, W candidate windows, R run slots.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from . import accounting as acc
from .units import ONE, ZERO, q_g

if TYPE_CHECKING:  # pragma: no cover
    from .engine import Engine, SimJob

URGENT_SLACK_SLOTS = 2
SAFETY_MARGIN_SLOTS = 2
MAX_REPAIR_PASSES = 3
TIE_TOLERANCE = Decimal("10")  # gCO2e/kWh
MAX_PLAN_SPAN = 288  # 3 days of slots


def credit_potential(eng: "Engine", job: "SimJob", t: int) -> Decimal:
    """Expected credit if the job ran in slot t: E × (baseline − I(t))."""
    from .engine import slots_needed

    baseline = job.baseline_intensity
    if baseline is None:
        baseline = eng.curve.window_avg(t, slots_needed(job.remaining_min, ONE, job.slot_minutes))
    return acc.estimated_savings_g(job.energy_full_kwh, baseline, eng.intensity(t))


@dataclass
class Placement:
    job: "SimJob"
    start: int | None
    need: int
    window_avg: Decimal | None
    now_avg: Decimal
    green: bool
    forced: bool
    deliberate: bool
    est_savings_g: Decimal
    est_debt_g: Decimal
    est_credit_g: Decimal
    reason: str

    def details(self) -> dict[str, Any]:
        return {
            "planned_start_slot": self.start,
            "window_avg_intensity": str(self.window_avg) if self.window_avg is not None else None,
            "now_avg_intensity": str(self.now_avg),
            "green_window": self.green,
            "est_savings_g": str(self.est_savings_g),
            "est_debt_g": str(self.est_debt_g),
            "est_credit_g": str(self.est_credit_g),
        }


@dataclass
class Plan:
    slot: int
    placements: list[Placement]
    projection: list[tuple[int, Decimal]] = field(default_factory=list)
    peak_g: Decimal = ZERO
    end_balance_g: Decimal = ZERO
    repayable_g: Decimal = ZERO
    projected_new_debt_g: Decimal = ZERO
    start_debt_g: Decimal = ZERO
    horizon_end: int = 0


def build_plan(eng: "Engine", t: int) -> Plan:
    from .engine import slots_needed
    from .policies import fmt_g, fmt_i

    cfg = eng.config
    curve = eng.curve
    waiting = eng.ready_jobs(emergency=False)
    end = t + cfg.planning_horizon_slots
    if waiting:
        end = max(end, max(j.deadline_slot for j in waiting))
    end = min(end, t + MAX_PLAN_SPAN)
    span = end - t + 1
    free: list[Decimal] = [Decimal(cfg.workers - cfg.emergency_reserve)] * span
    finish_events: list[tuple[int, Decimal, Decimal]] = []  # (slot, extra debt, expected credit) for running jobs

    for job in eng.active_jobs():
        cap = job.capacity if job.capacity > ZERO else ONE  # paused jobs are assumed to resume at full speed
        start = t + (1 if job.capacity <= ZERO else 0)
        fin = start + slots_needed(job.remaining_min, cap, job.slot_minutes)
        if not job.is_emergency:
            for s in range(start, min(fin, end + 1)):
                free[s - t] -= cap
        rem_energy = acc.energy_kwh(acc.throttled_power_w(job.power_w, cap, cfg.static_power_fraction),
                                    job.remaining_min / cap)
        avg = curve.window_avg(start, max(fin - start, 1))
        credit = ZERO
        if job.deferred_by_controller and job.baseline_intensity is not None and fin <= job.deadline_slot:
            credit = acc.counterfactual_credit_g(job.energy_full_kwh, job.baseline_intensity,
                                                 job.emissions_g + acc.gross_emissions_g(rem_energy, avg))
        finish_events.append((fin, acc.debt_g(rem_energy, avg, cfg.debt_intensity_threshold), credit))
    extra_emerg = max(ZERO, sum((j.capacity for j in eng.active_jobs() if j.is_emergency), ZERO)
                      - cfg.emergency_reserve)
    if extra_emerg > ZERO:
        for s in range(t, min(t + 4, end + 1)):
            free[s - t] -= extra_emerg

    debt0 = eng.effective_debt()
    inversion = debt0 > ZERO

    def order(j: "SimJob") -> tuple:
        # Capacity is reserved earliest-deadline-first (protects feasibility); repayment value
        # (during debt) or nominal priority only breaks ties.
        value = -credit_potential(eng, j, t) if inversion else Decimal(j.priority)
        return (j.deadline_slot, value, j.id)

    ordered = sorted(waiting, key=order)
    base_free = list(free)
    asap: dict[str, str] = {}  # job id → id of the job it protects
    placements: list[Placement] = []
    for _attempt in range(MAX_REPAIR_PASSES):
        placements, infeasible = _plan_pass(eng, t, end, ordered, list(base_free), debt0, asap)
        if infeasible is None:
            break
        # Repair: delayed jobs with earlier deadlines go ASAP so the infeasible job gets a window.
        idx = next(i for i, p in enumerate(placements) if p.job.id == infeasible)
        newly = {p.job.id for p in placements[:idx] if p.start is not None and p.start > t and p.job.id not in asap}
        if not newly:
            break
        asap.update({jid: infeasible for jid in newly})

    plan = Plan(slot=t, placements=placements, start_debt_g=debt0, horizon_end=end)
    _project(plan, eng, t, end, finish_events)
    return plan


def _plan_pass(eng: "Engine", t: int, end: int, ordered: list["SimJob"], free: list[Decimal], debt0: Decimal,
               asap: dict[str, str]) -> tuple[list[Placement], str | None]:
    from .engine import slots_needed
    from .policies import fmt_g, fmt_i

    cfg = eng.config
    curve = eng.curve
    inversion = debt0 > ZERO
    placements: list[Placement] = []
    infeasible: str | None = None
    for job in ordered:
        need = max(slots_needed(job.remaining_min, ONE, job.slot_minutes), 1)
        latest = min(job.deadline_slot - need, end - need + 1)
        # Keep a safety margin before the deadline (an emergency may take capacity later) when slack allows.
        margin = min(SAFETY_MARGIN_SLOTS, max(0, (latest - t) // 4))
        latest_safe = latest - margin
        now_avg = curve.window_avg(t, need)
        energy = job.energy_full_kwh

        def fits(s: int) -> bool:
            return all(free[x - t] >= 1 for x in range(s, s + need))

        now_ok = t <= latest and fits(t)
        if eng.starving(job, t) and fits(t):
            placements.append(_place(job, t, need, now_avg, now_avg, False, True, False, energy, cfg,
                                     f"Maximum wait of {job.max_wait_min} min reached (starvation guard)."))
            _reserve(free, t, t, need)
            continue
        candidates = [s for s in range(t, latest_safe + 1) if fits(s)] or \
            [s for s in range(t, latest + 1) if fits(s)]
        if not candidates:
            if infeasible is None:
                infeasible = job.id
            if fits(t):
                reason = (f"No window with free capacity can finish before {eng.hhmm(job.deadline_slot)}; "
                          f"running now to minimise lateness (deadline at risk).")
                placements.append(_place(job, t, need, now_avg, now_avg, False, True, False, energy, cfg, reason))
                _reserve(free, t, t, need)
            else:
                placements.append(_place(job, None, need, None, now_avg, False, True, False, energy, cfg,
                                         "No free worker now and no feasible window; waiting for capacity."))
            continue

        if job.id in asap:
            chosen = candidates[0]
            avg = curve.window_avg(chosen, need)
            reason = (f"Scheduled at its earliest feasible slot ({eng.hhmm(chosen)}) for deadline protection: "
                      f"delaying it further would leave {asap[job.id]} without a feasible window before its deadline.")
            placements.append(_place(job, chosen, need, avg, now_avg, curve.window_max(chosen, need) <= cfg.green_threshold,
                                     chosen == t, False, energy, cfg, reason))
            _reserve(free, t, chosen, need)
            continue

        scored = [(curve.window_avg(s, need), s) for s in candidates]
        pool = scored
        forced_dirty = False
        if inversion:
            green_pool = [(a, s) for a, s in scored if curve.window_max(s, need) <= cfg.green_threshold]
            if green_pool:
                pool = green_pool
            else:
                forced_dirty = True
        best = min(a for a, _ in pool)
        chosen_avg, chosen = min(((a, s) for a, s in pool if a <= best + TIE_TOLERANCE), key=lambda x: x[1])
        saving = acc.estimated_savings_g(energy, now_avg, chosen_avg)
        not_worth = False
        if chosen != t and not inversion and now_ok and saving < cfg.min_deferral_savings_g:
            chosen, chosen_avg, not_worth = t, now_avg, True
            saving = ZERO
        green = curve.window_max(chosen, need) <= cfg.green_threshold
        deadline = eng.hhmm(job.deadline_slot)

        if chosen == t:
            if not_worth:
                reason = (f"Runs now: the best feasible window saves under {fmt_g(cfg.min_deferral_savings_g)} g, "
                          f"not worth the delay.")
            elif forced_dirty:
                reason = (f"No fully green window fits before {deadline}; now is the least-carbon feasible window "
                          f"({fmt_i(now_avg)} gCO₂e/kWh). Deadline protection overrides green-only repayment.")
            elif inversion and green:
                reason = (f"Green window now ({fmt_i(now_avg)} gCO₂e/kWh) with {fmt_g(debt0)} g debt outstanding: "
                          f"scheduled as repayment work (ranked by repayment value — priority inversion).")
            else:
                reason = f"Forecast shows no cleaner feasible window before {deadline}; runs now at {fmt_i(now_avg)} gCO₂e/kWh."
            placements.append(_place(job, t, need, now_avg, now_avg, green, forced_dirty, False, energy, cfg, reason))
        else:
            why = []
            why.append(f"projected intensity falls from {fmt_i(now_avg)} to {fmt_i(chosen_avg)} gCO₂e/kWh "
                       f"(est. saving {fmt_g(saving)} g)")
            why.append(f"the deadline {deadline} remains feasible (latest start {eng.hhmm(job.deadline_slot - need)})")
            if inversion:
                why.append(f"{fmt_g(debt0)} g debt is outstanding, so flexible work is restricted to "
                           f"{'green' if green else 'the least-carbon'} slots")
            verb = "Deferred" if now_ok else "Planned"
            reason = f"{verb} until {eng.hhmm(chosen)} because " + ", ".join(why[:-1]) + ", and " + why[-1] + "."
            if not now_ok:
                reason += " (No free worker now — capacity wait, not a credit-bearing deferral.)"
            placements.append(_place(job, chosen, need, chosen_avg, now_avg, green, False, now_ok, energy, cfg, reason))
        _reserve(free, t, chosen, need)
    return placements, infeasible


def _reserve(free: list[Decimal], t: int, start: int, need: int) -> None:
    for s in range(start, start + need):
        if 0 <= s - t < len(free):
            free[s - t] -= ONE


def _place(job, start, need, window_avg, now_avg, green, forced, deliberate, energy, cfg, reason) -> Placement:
    avg = window_avg if window_avg is not None else now_avg
    baseline = job.baseline_intensity if job.baseline_intensity is not None else now_avg
    deferred = job.deferred_by_controller or deliberate
    est_credit = acc.estimated_savings_g(energy, baseline, avg) if deferred else ZERO
    return Placement(
        job=job,
        start=start,
        need=need,
        window_avg=window_avg,
        now_avg=now_avg,
        green=green,
        forced=forced,
        deliberate=deliberate,
        est_savings_g=acc.estimated_savings_g(energy, now_avg, avg),
        est_debt_g=acc.debt_g(energy, avg, cfg.debt_intensity_threshold),
        est_credit_g=est_credit,
        reason=reason,
    )


def _project(plan: Plan, eng: "Engine", t: int, end: int, finish_events: list[tuple[int, Decimal, Decimal]]) -> None:
    debits: dict[int, Decimal] = {}
    credits: dict[int, Decimal] = {}
    for slot, debt, credit in finish_events:
        debits[slot] = debits.get(slot, ZERO) + debt
        credits[slot] = credits.get(slot, ZERO) + credit
    for p in plan.placements:
        fin = (p.start if p.start is not None else t) + p.need
        debits[fin] = debits.get(fin, ZERO) + p.est_debt_g
        credits[fin] = credits.get(fin, ZERO) + p.est_credit_g
    balance = plan.start_debt_g
    peak = balance
    points = [(t, q_g(balance))]
    for s in range(t + 1, end + 2):
        if s in debits or s in credits:
            balance += debits.get(s, ZERO)
            balance = max(ZERO, balance - credits.get(s, ZERO))
            peak = max(peak, balance)
            points.append((s, q_g(balance)))
    plan.projection = points
    plan.peak_g = q_g(peak)
    plan.end_balance_g = q_g(balance)
    plan.repayable_g = q_g(sum((p.est_credit_g for p in plan.placements), ZERO))
    plan.projected_new_debt_g = q_g(sum(debits.values(), ZERO))
