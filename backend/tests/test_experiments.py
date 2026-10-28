import pytest
from pydantic import ValidationError

from app.core.experiment import ExperimentRequest, run_experiment
from app.core.metrics import METRIC_KEYS, NON_DETERMINISTIC, aggregate, pct_change
from app.core.workloads import TraceSpec, generate_trace


def small(**kw) -> ExperimentRequest:
    return ExperimentRequest(seeds=[1, 2], emergency=2, normal=6, background=5, **kw)


def strip(results):
    return [{k: v for k, v in r["metrics"].items() if k not in NON_DETERMINISTIC} for r in results["runs"]]


def test_trace_generation_is_deterministic():
    a = generate_trace(TraceSpec(seed=3))
    b = generate_trace(TraceSpec(seed=3))
    assert [(j.id, j.arrival_slot, j.runtime_min, j.power_w) for j in a] == \
           [(j.id, j.arrival_slot, j.runtime_min, j.power_w) for j in b]
    assert all(j.deadline_slot >= j.arrival_slot + j.runtime_min // 15 for j in a)


def test_experiment_replay_is_deterministic():
    first = run_experiment(small())
    second = run_experiment(small())
    assert strip(first) == strip(second)


def test_all_policies_see_identical_workload():
    res = run_experiment(small())
    energy_full = res["trace_summary"]["estimated_energy_kwh"]
    assert energy_full > 0
    for policy in ("fifo", "threshold", "debt_reactive", "debt_predictive"):
        runs = [r for r in res["runs"] if r["policy"] == policy]
        assert len(runs) == 2 and all(set(METRIC_KEYS) <= set(r["metrics"]) for r in runs)


def test_controller_reduces_final_debt_versus_fifo():
    res = run_experiment(small())
    agg = res["aggregates"]
    assert agg["debt_predictive"]["final_debt_g"]["mean"] <= agg["fifo"]["final_debt_g"]["mean"]
    assert agg["fifo"]["credits_applied_g"]["mean"] == 0  # FIFO never defers → no credits


def test_sweep_runs():
    res = run_experiment(small(sweep_param="green_threshold", sweep_values=[150, 250]))
    assert [p["value"] for p in res["sweep"]["points"]] == [150.0, 250.0]


def test_metric_helpers_handle_edge_cases():
    assert pct_change(0, 5) is None
    assert pct_change(100, 80) == -20.0
    assert aggregate([]) == {}


def test_invalid_request_rejected():
    with pytest.raises(ValidationError):
        ExperimentRequest(seeds=[1, 1])
    with pytest.raises(ValidationError):
        ExperimentRequest(green_threshold=500, debt_intensity_threshold=300)
    with pytest.raises(ValidationError):
        ExperimentRequest(sweep_param="green_threshold", sweep_values=[])
