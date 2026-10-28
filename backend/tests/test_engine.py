from decimal import Decimal

import pytest

from app.core.carbon_curve import CarbonCurve, simulated_curve
from app.core.config_model import ControllerConfig
from app.core.engine import Engine, InvalidTransition, JobState, SimJob
from app.core.hashchain import verify_chain
from app.core.ledger import EventType
from app.core.policies import make_policy, min_feasible_capacity
from app.core.workloads import SCENARIO_END_SLOT


def flat_curve(values: list[int]) -> CarbonCurve:
    return CarbonCurve([Decimal(v) for v in values], ["SIMULATED"] * len(values))


def job(id_: str, cls: str, arrival: int, deadline: int, runtime: int = 30, power: int = 1000, prio: int = 3) -> SimJob:
    return SimJob(id=id_, name=id_, workload="w", job_class=cls, priority=prio, power_w=Decimal(power),
                  runtime_min=runtime, arrival_slot=arrival, deadline_slot=deadline)


def run(eng: Engine, until: int) -> Engine:
    eng.run_until(until)
    return eng


def test_emergency_runs_immediately_in_high_carbon_slot():
    curve = flat_curve([700] * 8 + [100] * 40)
    eng = Engine(ControllerConfig(), curve, [job("E", "emergency", 0, 6, 60)], make_policy("debt_predictive"))
    eng.step()
    e = eng.jobs["E"]
    assert e.state == JobState.RUNNING and e.start_slot == 0
    run(eng, 6)
    assert e.state == JobState.COMPLETED and e.debt_g == Decimal("350.000")  # 1 kWh × (700 − 350)
    assert eng.ledger.balance_g == Decimal("350.000")


def test_emergency_reserve_keeps_a_worker_free():
    cfg = ControllerConfig(workers=2, emergency_reserve=1)
    curve = flat_curve([100] * 48)
    jobs = [job("N1", "normal", 0, 40, 120), job("N2", "normal", 0, 40, 120), job("E", "emergency", 1, 6, 30)]
    eng = Engine(cfg, curve, jobs, make_policy("fifo"))
    run(eng, 2)
    assert eng.jobs["N2"].state == JobState.QUEUED  # only one flexible worker
    assert eng.jobs["E"].start_slot == 1


@pytest.mark.parametrize("policy", ["threshold", "debt_reactive", "debt_predictive"])
def test_never_defers_past_deadline(policy):
    # Dirty now, green later, but the deadline is before the green window → must run now.
    curve = flat_curve([600] * 8 + [100] * 40)
    eng = Engine(ControllerConfig(policy=policy), curve, [job("N", "normal", 0, 3, 45)], make_policy(policy))
    run(eng, 10)
    n = eng.jobs["N"]
    assert n.start_slot == 0 and not n.deadline_missed and n.finish_slot <= n.deadline_slot


def test_deferral_records_baseline_and_credit_is_verified(demo_engine):
    eng = run(demo_engine(), SCENARIO_END_SLOT)
    etl = eng.jobs["J-0004"]
    assert etl.deferred_by_controller and etl.baseline_intensity is not None
    assert etl.start_slot is not None and eng.is_green(etl.start_slot)
    recs = [r for r in eng.ledger.new_records if r.job_id == "J-0004"]
    deferral = next(r for r in recs if r.event_type == EventType.DEFERRAL_RECORDED)
    credit = next(r for r in recs if r.event_type == EventType.CREDIT_VERIFIED)
    assert credit.reference_event_id == deferral.event_id
    assert credit.intensity_baseline == deferral.intensity_baseline
    assert Decimal(credit.details["credit_earned_g"]) > 0


def test_emergency_to_green_scenario_clears_debt(demo_engine):
    eng = run(demo_engine(), SCENARIO_END_SLOT)
    types = [r.event_type for r in eng.ledger.new_records]
    assert EventType.DEBT_INCURRED in types and EventType.CREDIT_VERIFIED in types
    assert types[-1] == EventType.DEBT_CLEARED
    assert eng.ledger.balance_g == 0
    assert eng.ledger.total_debt_g == eng.ledger.total_credit_applied_g  # no over-crediting
    assert eng.ledger.total_credit_earned_g > eng.ledger.total_credit_applied_g  # surplus not banked
    assert not any(j.deadline_missed for j in eng.jobs.values())
    assert any(d.action == "REPAYMENT_START" for d in eng.new_decisions)
    assert verify_chain([r.as_dict() for r in eng.ledger.new_records]).ok


def test_priority_inversion_ranks_by_repayment_value(demo_engine):
    eng = run(demo_engine(), SCENARIO_END_SLOT)
    sweep, etl = eng.jobs["J-0005"], eng.jobs["J-0004"]  # background p5 vs normal p3
    assert sweep.priority > etl.priority
    starts = [d for d in eng.new_decisions if d.action == "REPAYMENT_START"]
    assert starts[0].job_id == "J-0005"  # lower nominal priority, larger repayment value, ranked first


def test_no_credit_without_controller_deferral():
    curve = flat_curve([100] * 48)
    eng = Engine(ControllerConfig(), curve, [job("N", "normal", 0, 20, 30)], make_policy("debt_predictive"))
    run(eng, 10)
    assert eng.jobs["N"].state == JobState.COMPLETED
    assert not any(r.event_type.startswith("CREDIT") for r in eng.ledger.new_records)


def test_operator_run_voids_credit(demo_engine):
    eng = demo_engine()
    run(eng, 30)  # 07:30 — ETL is deferred by now
    etl = eng.jobs["J-0004"]
    assert etl.state == JobState.DEFERRED and etl.deferred_by_controller
    eng.operator_run(etl)
    run(eng, SCENARIO_END_SLOT)
    denied = [r for r in eng.ledger.new_records if r.job_id == "J-0004" and r.event_type == EventType.CREDIT_DENIED]
    assert denied and "voided" in " ".join(denied[0].details["reasons"])


def test_late_job_gets_no_credit():
    # Deferred to a green window, then a long emergency blocks capacity so the job finishes late.
    cfg = ControllerConfig(workers=2, emergency_reserve=1)
    curve = flat_curve([600] * 4 + [100] * 60)
    jobs = [job("N", "normal", 0, 8, 60), job("E", "emergency", 4, 30, 600), job("E2", "emergency", 4, 30, 600)]
    eng = Engine(cfg, curve, jobs, make_policy("debt_predictive"))
    run(eng, 60)
    n = eng.jobs["N"]
    assert n.deferred_by_controller and n.deadline_missed
    assert any(r.job_id == "N" and r.event_type == EventType.CREDIT_DENIED for r in eng.ledger.new_records)


def test_throttle_levels_by_band_and_deadline_safety():
    j = job("B", "background", 0, 40, 60)
    assert min_feasible_capacity(j, 0, Decimal("0")) == Decimal("0")  # lots of slack → pause allowed
    tight = job("B2", "background", 0, 4, 60)
    assert min_feasible_capacity(tight, 0, Decimal("0")) == Decimal("1")  # zero slack → full speed
    medium = job("B3", "background", 0, 10, 60)  # 50% needs 8 slots + 2-slot safety margin = 10
    assert min_feasible_capacity(medium, 0, Decimal("0.2")) == Decimal("0.5")
    edge = job("B4", "background", 0, 9, 60)  # 50% would end inside the margin → stays at full speed
    assert min_feasible_capacity(edge, 0, Decimal("0.2")) == Decimal("1")


def test_progressive_throttling_in_scenario(demo_engine):
    eng = run(demo_engine(), SCENARIO_END_SLOT)
    log_job = eng.jobs["J-0001"]
    actions = [d.action for d in eng.new_decisions if d.job_id == "J-0001"]
    assert "THROTTLE" in actions and "PAUSE" in actions
    assert not log_job.deadline_missed
    assert all(d.capacity in (None, Decimal("1")) for d in eng.new_decisions
               if d.job_id in ("J-0002", "J-0006") and d.action in ("THROTTLE", "PAUSE"))  # emergencies untouched


def test_invalid_transitions_rejected():
    j = job("X", "normal", 0, 10)
    with pytest.raises(InvalidTransition):
        Engine.transition(j, JobState.COMPLETED)
    j.state = JobState.COMPLETED
    with pytest.raises(InvalidTransition):
        Engine.transition(j, JobState.RUNNING)


def test_failed_job_books_debt_and_no_credit():
    curve = flat_curve([600] * 48)
    j = job("F", "emergency", 0, 10, 60)
    j.simulate_failure = True
    eng = Engine(ControllerConfig(), curve, [j], make_policy("debt_predictive"))
    run(eng, 10)
    assert j.state == JobState.FAILED and j.debt_booked and j.debt_g > 0


def test_predictive_differs_from_reactive(demo_engine):
    pred = run(demo_engine("debt_predictive"), SCENARIO_END_SLOT)
    reac = run(demo_engine("debt_reactive"), SCENARIO_END_SLOT)
    # The reactive controller starts repayment at the first green slot; the predictive planner places work
    # in the lowest-carbon window it can see.
    assert pred.jobs["J-0004"].start_slot != reac.jobs["J-0004"].start_slot
    assert pred.jobs["J-0004"].emissions_g < reac.jobs["J-0004"].emissions_g
    assert pred.last_plan is not None and reac.last_plan is None


def test_curve_is_deterministic():
    a = simulated_curve("solar_midday", 7, 3)
    b = simulated_curve("solar_midday", 7, 3)
    c = simulated_curve("solar_midday", 8, 3)
    assert a.values == b.values and a.values != c.values
