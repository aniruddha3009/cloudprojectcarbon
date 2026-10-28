"""Carbon accounting formulas.

    gross_emissions_g = energy_kwh × actual_intensity
    debt_g            = energy_kwh × max(0, actual_intensity − I_threshold)
    savings_g         = energy_kwh × max(0, current_intensity − candidate_intensity)
    credit_g          = max(0, E_counterfactual × I_baseline − actual_emissions_g)

The credit formula is a conservative generalisation of
``energy × max(0, baseline − actual)``: when a job is throttled its actual energy
can be *higher* than the counterfactual full-speed energy, and comparing total
emissions (not intensities) charges that penalty against the credit.

Debt is "policy-defined excess-carbon debt": the portion of emissions caused by
running above a configured intensity threshold. It is an accounting quantity.
Repayment credits reward *future avoided* emissions; they never erase emissions
that physically happened.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .units import ONE, ZERO, D, Number, q_g, q_kwh, q_w


def energy_kwh(power_w: Number, minutes: Number) -> Decimal:
    """Energy for a constant power draw: W × min / 60 / 1000."""
    return q_kwh(D(power_w) * D(minutes) / Decimal(60) / Decimal(1000))


def throttled_power_w(power_w: Number, capacity: Number, static_fraction: Number) -> Decimal:
    """Power at a capacity fraction using a static + dynamic model.

    P(c) = P_full × (s + (1 − s) × c)   for c > 0,   P(0) = 0 (paused, checkpointed).
    Because the static share s is drawn regardless of speed while work takes
    1/c times longer, energy per unit of work *increases* when throttled.
    """
    c = D(capacity)
    if c <= ZERO:
        return Decimal("0.000")
    s = D(static_fraction)
    return q_w(D(power_w) * (s + (ONE - s) * c))


def gross_emissions_g(energy: Number, intensity: Number) -> Decimal:
    return q_g(D(energy) * D(intensity))


def debt_g(energy: Number, intensity: Number, threshold: Number) -> Decimal:
    excess = D(intensity) - D(threshold)
    return q_g(D(energy) * excess) if excess > ZERO else Decimal("0.000")


def estimated_savings_g(energy: Number, current_intensity: Number, candidate_intensity: Number) -> Decimal:
    delta = D(current_intensity) - D(candidate_intensity)
    return q_g(D(energy) * delta) if delta > ZERO else Decimal("0.000")


def counterfactual_credit_g(
    counterfactual_energy_kwh: Number, baseline_intensity: Number, actual_emissions_g: Number
) -> Decimal:
    value = D(counterfactual_energy_kwh) * D(baseline_intensity) - D(actual_emissions_g)
    return q_g(value) if value > ZERO else Decimal("0.000")


@dataclass
class CreditDecision:
    eligible: bool
    credit_g: Decimal
    reasons: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)


def evaluate_credit(
    *,
    deferred_by_controller: bool,
    deferral_event_id: str | None,
    baseline_intensity: Decimal | None,
    completed: bool,
    finished_slot: int | None,
    deadline_slot: int,
    already_credited: bool,
    void_reason: str | None,
    counterfactual_energy_kwh: Decimal,
    actual_emissions_g: Decimal,
) -> CreditDecision:
    """Apply every eligibility rule; all must pass for a credit to be granted."""
    checks = {
        "deferred_by_controller": bool(deferred_by_controller and deferral_event_id),
        "baseline_recorded": baseline_intensity is not None,
        "completed_successfully": completed,
        "met_deadline": finished_slot is not None and finished_slot <= deadline_slot,
        "not_already_credited": not already_credited,
        "no_operator_override": void_reason is None,
    }
    reasons: list[str] = []
    if not checks["deferred_by_controller"]:
        reasons.append("job was not deliberately deferred by the controller (no deferral event)")
    if not checks["baseline_recorded"]:
        reasons.append("no counterfactual baseline intensity was recorded at deferral time")
    if not checks["completed_successfully"]:
        reasons.append("job did not complete successfully")
    if not checks["met_deadline"]:
        reasons.append("job finished after its deadline")
    if not checks["not_already_credited"]:
        reasons.append("a credit was already issued for this job")
    if not checks["no_operator_override"]:
        reasons.append(f"credit voided: {void_reason}")

    credit = ZERO
    if all(checks.values()):
        credit = counterfactual_credit_g(counterfactual_energy_kwh, baseline_intensity or ZERO, actual_emissions_g)
        checks["positive_avoided_emissions"] = credit > ZERO
        if credit <= ZERO:
            reasons.append("actual emissions were not lower than the counterfactual baseline")
    eligible = all(checks.values())
    if eligible:
        reasons.append("deferred by controller with recorded baseline, completed within deadline, first credit")
    return CreditDecision(eligible=eligible, credit_g=q_g(credit) if eligible else Decimal("0.000"), reasons=reasons, checks=checks)
