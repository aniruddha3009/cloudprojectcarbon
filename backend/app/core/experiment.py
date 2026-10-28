"""Experiment runner: replays identical traces and carbon curves across policies.

Fairness guarantees:
  * For each seed, one workload trace and one carbon curve are generated and
    every policy receives a fresh, identical copy of them.
  * Energy model, accounting rules, capacity and deadlines are identical.
  * Runs stop when every job is settled or at the 3-day horizon.
"""

from __future__ import annotations

import platform
import sys
from decimal import Decimal
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .carbon_curve import SLOTS_PER_DAY, simulated_curve
from .config_model import ControllerConfig, PolicyName, ProfileName
from .engine import Engine
from .metrics import METRIC_KEYS, METRIC_LABELS, aggregate, compute_metrics, pct_change
from .policies import POLICIES, make_policy
from .workloads import TraceSpec, generate_trace

MAX_SLOTS = 3 * SLOTS_PER_DAY
SweepParam = Literal["debt_intensity_threshold", "green_threshold", "debt_hard_g", "static_power_fraction"]


class ExperimentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="Policy comparison", min_length=1, max_length=120)
    seeds: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5], min_length=1, max_length=20)
    policies: list[PolicyName] = Field(default_factory=lambda: ["fifo", "threshold", "debt_reactive", "debt_predictive"],
                                       min_length=1)
    emergency: int = Field(default=4, ge=0, le=20)
    normal: int = Field(default=18, ge=0, le=60)
    background: int = Field(default=14, ge=0, le=60)
    profile: ProfileName = "solar_midday"
    noise_pct: Decimal = Field(default=Decimal("3"), ge=0, le=25)
    debt_intensity_threshold: Decimal = Field(default=Decimal("350"), ge=0, le=2000)
    green_threshold: Decimal = Field(default=Decimal("200"), ge=0, le=2000)
    debt_soft_g: Decimal = Field(default=Decimal("100"), ge=0)
    debt_hard_g: Decimal = Field(default=Decimal("400"), ge=0)
    debt_critical_g: Decimal = Field(default=Decimal("800"), ge=0)
    static_power_fraction: Decimal = Field(default=Decimal("0.30"), ge=0, le=Decimal("0.9"))
    workers: int = Field(default=4, ge=1, le=64)
    emergency_reserve: int = Field(default=1, ge=0, le=16)
    sweep_param: SweepParam | None = None
    sweep_values: list[Decimal] = Field(default_factory=list, max_length=8)
    sweep_policy: PolicyName = "debt_predictive"

    @model_validator(mode="after")
    def _check(self) -> "ExperimentRequest":
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError("seeds must be unique")
        if any(s < 0 for s in self.seeds):
            raise ValueError("seeds must be non-negative")
        if self.emergency + self.normal + self.background == 0:
            raise ValueError("the trace must contain at least one job")
        if self.sweep_param and not self.sweep_values:
            raise ValueError("sweep_values are required when sweep_param is set")
        self.base_config()  # validates threshold relationships
        if self.sweep_param:
            for v in self.sweep_values:
                self.base_config(**{self.sweep_param: v})
        return self

    def base_config(self, **overrides: Any) -> ControllerConfig:
        data = {k: getattr(self, k) for k in ("profile", "noise_pct", "debt_intensity_threshold", "green_threshold",
                                              "debt_soft_g", "debt_hard_g", "debt_critical_g",
                                              "static_power_fraction", "workers", "emergency_reserve")}
        data.update(overrides)
        return ControllerConfig(**data)

    def trace_spec(self, seed: int) -> TraceSpec:
        return TraceSpec(seed=seed, emergency=self.emergency, normal=self.normal, background=self.background)

    def total_units(self) -> int:
        return len(self.seeds) * len(self.policies) + len(self.seeds) * len(self.sweep_values)


def run_single(cfg: ControllerConfig, trace: TraceSpec, policy: str, keep_timeline: bool = False) -> tuple[dict[str, Any], list]:
    cfg = cfg.model_copy(update={"policy": policy, "seed": trace.seed})
    curve = simulated_curve(cfg.profile, trace.seed, cfg.noise_pct, days=3)
    eng = Engine(cfg, curve, generate_trace(trace), make_policy(policy), now=0)
    while eng.now < MAX_SLOTS and not eng.all_settled():
        eng.step()
    metrics = compute_metrics(eng)
    series = []
    if keep_timeline:
        series = [{"slot": p.slot, "intensity": float(p.intensity), "effective_debt_g": float(p.effective_debt_g),
                   "cum_emissions_g": float(p.cum_emissions_g), "cum_credit_g": float(p.cum_credit_g),
                   "running": p.running, "deferred": p.deferred} for p in eng.new_timeline]
    return metrics, series


def run_experiment(req: ExperimentRequest, progress: Callable[[float], None] | None = None) -> dict[str, Any]:
    total = max(req.total_units(), 1)
    done = 0
    runs: list[dict[str, Any]] = []
    timeseries: dict[str, list] = {}
    base = req.base_config()
    for i, seed in enumerate(req.seeds):
        spec = req.trace_spec(seed)
        for policy in req.policies:
            metrics, series = run_single(base, spec, policy, keep_timeline=(i == 0))
            runs.append({"policy": policy, "seed": seed, "metrics": metrics})
            if i == 0:
                timeseries[policy] = series
            done += 1
            if progress:
                progress(done / total)

    aggregates = {p: aggregate([r["metrics"] for r in runs if r["policy"] == p]) for p in req.policies}
    reference = "fifo" if "fifo" in req.policies else req.policies[0]
    comparisons = {
        p: {k: pct_change(aggregates[reference][k]["mean"], aggregates[p][k]["mean"]) for k in METRIC_KEYS}
        for p in req.policies
    }

    sweep: list[dict[str, Any]] = []
    if req.sweep_param:
        for value in req.sweep_values:
            cfg = req.base_config(**{req.sweep_param: value})
            vals = []
            for seed in req.seeds:
                metrics, _ = run_single(cfg, req.trace_spec(seed), req.sweep_policy)
                vals.append(metrics)
                done += 1
                if progress:
                    progress(done / total)
            sweep.append({"value": float(value), "aggregates": aggregate(vals)})

    first_trace = generate_trace(req.trace_spec(req.seeds[0]))
    return {
        "reference_policy": reference,
        "policies": [{"name": p, "label": POLICIES[p].label, "uses_forecast": POLICIES[p].uses_forecast,
                      "debt_aware": POLICIES[p].debt_aware} for p in req.policies],
        "metric_labels": {k: {"label": v[0], "unit": v[1]} for k, v in METRIC_LABELS.items()},
        "runs": runs,
        "aggregates": aggregates,
        "comparisons_vs_reference_pct": comparisons,
        "timeseries_seed": req.seeds[0],
        "timeseries": timeseries,
        "sweep": {"param": req.sweep_param, "policy": req.sweep_policy, "points": sweep} if req.sweep_param else None,
        "trace_summary": {
            "seed": req.seeds[0], "jobs": len(first_trace),
            "by_class": {c: sum(1 for j in first_trace if j.job_class == c) for c in ("emergency", "normal", "background")},
            "estimated_energy_kwh": float(sum((j.energy_full_kwh for j in first_trace), Decimal(0))),
        },
        "environment": {"python": sys.version.split()[0], "platform": platform.platform(),
                        "processor": platform.processor() or platform.machine()},
        "methodology": [
            "Identical seeded workload trace and carbon curve for every policy within a seed.",
            "Energy is estimated from declared power and runtime (static + dynamic throttle model); all readings SIMULATED.",
            "Metrics are means across seeds with sample standard deviation; decision overhead is measured wall time on this host and is not deterministic.",
            "Credits follow the verified-credit rules; surplus credit beyond outstanding debt is not banked.",
        ],
    }
