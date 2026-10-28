from decimal import Decimal

import pytest

from app.core import accounting as acc
from app.core.units import D


def test_energy_and_gross_emissions():
    energy = acc.energy_kwh(1500, 60)
    assert energy == Decimal("1.500000")
    assert acc.gross_emissions_g(energy, Decimal("620")) == Decimal("930.000")


def test_debt_only_above_threshold():
    assert acc.debt_g(Decimal("2"), Decimal("500"), Decimal("350")) == Decimal("300.000")
    assert acc.debt_g(Decimal("2"), Decimal("350"), Decimal("350")) == Decimal("0.000")
    assert acc.debt_g(Decimal("2"), Decimal("120"), Decimal("350")) == Decimal("0.000")


def test_savings_never_negative():
    assert acc.estimated_savings_g(Decimal("1"), Decimal("620"), Decimal("140")) == Decimal("480.000")
    assert acc.estimated_savings_g(Decimal("1"), Decimal("140"), Decimal("620")) == Decimal("0.000")


def test_throttled_power_and_energy_penalty():
    full = acc.throttled_power_w(1000, 1, Decimal("0.3"))
    half = acc.throttled_power_w(1000, Decimal("0.5"), Decimal("0.3"))
    assert full == Decimal("1000.000") and half == Decimal("650.000")
    assert acc.throttled_power_w(1000, 0, Decimal("0.3")) == Decimal("0.000")
    # 60 minutes of work: full speed = 1 h at 1000 W; half speed = 2 h at 650 W → more energy.
    assert acc.energy_kwh(half, 120) > acc.energy_kwh(full, 60)


def _credit(**overrides):
    args = dict(deferred_by_controller=True, deferral_event_id="LE-000001", baseline_intensity=Decimal("600"),
                completed=True, finished_slot=50, deadline_slot=60, already_credited=False, void_reason=None,
                counterfactual_energy_kwh=Decimal("1.0"), actual_emissions_g=Decimal("150"))
    args.update(overrides)
    return acc.evaluate_credit(**args)


def test_credit_granted_when_all_checks_pass():
    decision = _credit()
    assert decision.eligible and decision.credit_g == Decimal("450.000")


@pytest.mark.parametrize("override,reason", [
    ({"deferred_by_controller": False}, "not deliberately deferred"),
    ({"deferral_event_id": None}, "not deliberately deferred"),
    ({"baseline_intensity": None}, "baseline"),
    ({"completed": False}, "did not complete"),
    ({"finished_slot": 61}, "after its deadline"),
    ({"already_credited": True}, "already issued"),
    ({"void_reason": "operator override"}, "voided"),
    ({"actual_emissions_g": Decimal("700")}, "not lower"),
])
def test_credit_denied(override, reason):
    decision = _credit(**override)
    assert not decision.eligible
    assert decision.credit_g == Decimal("0.000")
    assert any(reason in r for r in decision.reasons)


def test_credit_charges_throttling_energy_penalty():
    # Counterfactual 1 kWh × 600 = 600 g. Throttled actual used 1.3 kWh × 150 = 195 g.
    decision = _credit(actual_emissions_g=Decimal("195"))
    assert decision.credit_g == Decimal("405.000")


def test_decimal_conversion_rejects_nan():
    with pytest.raises(ValueError):
        D(float("nan"))
