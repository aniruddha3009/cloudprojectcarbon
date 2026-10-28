"""Experiment metrics computed from a finished engine run."""

from __future__ import annotations

import statistics
from decimal import Decimal
from typing import Any

from .carbon_curve import SLOT_MINUTES
from .engine import Engine, JobState
from .units import ZERO, q_g, q_kwh

METRIC_KEYS = [
    "gross_emissions_g", "energy_kwh", "total_debt_g", "credits_applied_g", "credits_earned_g",
    "final_debt_g", "peak_debt_g", "deadline_misses", "emergency_deadline_misses", "avg_wait_min",
    "avg_delay_min", "deferrals", "jobs_deferred", "throttle_actions", "energy_per_job_kwh",
    "completed_jobs", "failed_or_unfinished", "decision_overhead_us", "clean_energy_pct",
]

METRIC_LABELS = {
    "gross_emissions_g": ("Gross estimated emissions", "gCO₂e"),
    "energy_kwh": ("Total estimated energy", "kWh"),
    "total_debt_g": ("Policy-defined debt incurred", "gCO₂e"),
    "credits_applied_g": ("Valid credits applied", "gCO₂e"),
    "credits_earned_g": ("Valid credits earned (incl. unbanked surplus)", "gCO₂e"),
    "final_debt_g": ("Final outstanding debt", "gCO₂e"),
    "peak_debt_g": ("Peak outstanding debt", "gCO₂e"),
    "deadline_misses": ("Deadline misses", "jobs"),
    "emergency_deadline_misses": ("Emergency deadline misses", "jobs"),
    "avg_wait_min": ("Average waiting time", "min"),
    "avg_delay_min": ("Average completion delay", "min"),
    "deferrals": ("Deferral decisions", "count"),
    "jobs_deferred": ("Jobs deferred by controller", "jobs"),
    "throttle_actions": ("Throttle/pause actions", "count"),
    "energy_per_job_kwh": ("Energy per completed job", "kWh"),
    "completed_jobs": ("Completed jobs", "jobs"),
    "failed_or_unfinished": ("Unfinished at horizon", "jobs"),
    "decision_overhead_us": ("Scheduler decision time per slot (measured)", "µs"),
    "clean_energy_pct": ("Clean-energy usage (share of energy used at or below the green threshold)", "%"),
}

# Metrics that depend on wall-clock timing and are excluded from determinism checks.
NON_DETERMINISTIC = {"decision_overhead_us"}


def compute_metrics(eng: Engine) -> dict[str, Any]:
    jobs = list(eng.jobs.values())
    completed = [j for j in jobs if j.state == JobState.COMPLETED]
    started = [j for j in jobs if j.start_slot is not None]
    waits = [(j.start_slot - j.arrival_slot) * SLOT_MINUTES for j in started]
    delays = [(j.finish_slot - j.arrival_slot) * SLOT_MINUTES - j.runtime_min for j in completed]
    energy = sum((j.energy_kwh for j in jobs), ZERO)
    peak = max((p.effective_debt_g for p in eng.new_timeline), default=ZERO)
    seg_energy = sum((seg.energy_kwh for seg in eng.new_segments), ZERO)
    clean_energy = sum((seg.energy_kwh for seg in eng.new_segments if seg.intensity <= eng.config.green_threshold), ZERO)
    return {
        "gross_emissions_g": float(q_g(sum((j.emissions_g for j in jobs), ZERO))),
        "energy_kwh": float(q_kwh(energy)),
        "total_debt_g": float(eng.ledger.total_debt_g),
        "credits_applied_g": float(eng.ledger.total_credit_applied_g),
        "credits_earned_g": float(eng.ledger.total_credit_earned_g),
        "final_debt_g": float(eng.ledger.balance_g),
        "peak_debt_g": float(peak),
        "deadline_misses": sum(1 for j in jobs if j.deadline_missed),
        "emergency_deadline_misses": sum(1 for j in jobs if j.deadline_missed and j.is_emergency),
        "avg_wait_min": round(statistics.fmean(waits), 2) if waits else 0.0,
        "avg_delay_min": round(statistics.fmean(delays), 2) if delays else 0.0,
        "deferrals": sum(j.deferral_count for j in jobs),
        "jobs_deferred": sum(1 for j in jobs if j.deferred_by_controller),
        "throttle_actions": sum(j.throttle_count for j in jobs),
        "energy_per_job_kwh": float(q_kwh(energy / len(completed))) if completed else 0.0,
        "completed_jobs": len(completed),
        "failed_or_unfinished": len(jobs) - len(completed),
        "decision_overhead_us": round(eng.decision_ns_total / max(eng.decision_calls, 1) / 1000, 2),
        "clean_energy_pct": round(float(clean_energy / seg_energy * 100), 2) if seg_energy > ZERO else 0.0,
    }


def aggregate(runs: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Mean, sample standard deviation, min and max of each metric across seeds."""
    out: dict[str, dict[str, float]] = {}
    for key in METRIC_KEYS:
        values = [float(r[key]) for r in runs]
        if not values:
            continue
        out[key] = {
            "mean": round(statistics.fmean(values), 3),
            "std": round(statistics.stdev(values), 3) if len(values) > 1 else 0.0,
            "min": round(min(values), 3),
            "max": round(max(values), 3),
        }
    return out


def pct_change(baseline: float, value: float) -> float | None:
    if baseline == 0:
        return None
    return round((value - baseline) / abs(baseline) * 100.0, 2)
