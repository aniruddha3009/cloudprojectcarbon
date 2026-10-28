"""Regenerates the quantitative results used in the documentation, proposal and poster.

Usage (from the project root):
    backend\\.venv\\Scripts\\python tools\\generate_results.py

Everything is produced by the same engine the application uses, with fixed seeds,
so re-running this script reproduces the published numbers exactly (except the
measured decision-overhead timing, which depends on the host).
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from app.core.carbon_curve import simulated_curve  # noqa: E402
from app.core.config_model import ControllerConfig  # noqa: E402
from app.core.engine import Engine  # noqa: E402
from app.core.experiment import ExperimentRequest, run_experiment  # noqa: E402
from app.core.hashchain import verify_chain  # noqa: E402
from app.core.metrics import METRIC_KEYS, compute_metrics  # noqa: E402
from app.core.policies import make_policy  # noqa: E402
from app.core.workloads import SCENARIO_END_SLOT, SCENARIO_START_SLOT, demo_sim_jobs  # noqa: E402

OUT = ROOT / "docs" / "results"
OUT.mkdir(parents=True, exist_ok=True)
COLORS = {"fifo": "#3987e5", "threshold": "#d95926", "debt_reactive": "#199e70", "debt_predictive": "#9085e9"}
SHORT = {"fifo": "FIFO", "threshold": "Threshold", "debt_reactive": "Debt controller", "debt_predictive": "Predictive"}

plt.rcParams.update({"font.family": "Segoe UI", "font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.edgecolor": "#888", "axes.grid": True, "axes.axisbelow": True, "grid.color": "#e5e5e5", "grid.linewidth": 0.6})


def scenario() -> dict:
    """The demo scenario under every policy (same 8 jobs, same curve)."""
    out = {}
    for policy in ("fifo", "threshold", "debt_reactive", "debt_predictive"):
        cfg = ControllerConfig(policy=policy)
        eng = Engine(cfg, simulated_curve(cfg.profile, cfg.seed, cfg.noise_pct), demo_sim_jobs(), make_policy(policy),
                     now=SCENARIO_START_SLOT)
        eng.run_until(SCENARIO_END_SLOT + 32)
        m = compute_metrics(eng)
        m["ledger_entries"] = len(eng.ledger.new_records)
        m["ledger_verified"] = verify_chain([r.as_dict() for r in eng.ledger.new_records]).ok
        out[policy] = m
        if policy == "debt_predictive":
            out["_predictive_ledger"] = [
                {"seq": r.seq, "event": r.event_type, "job": r.job_id, "sim_time": r.sim_time[11:16],
                 "amount_g": str(r.amount_g), "balance_after_g": str(r.balance_after_g),
                 "baseline": str(r.intensity_baseline) if r.intensity_baseline is not None else None,
                 "actual": str(r.intensity_actual) if r.intensity_actual is not None else None}
                for r in eng.ledger.new_records]
            out["_predictive_timeline"] = [{"slot": p.slot, "intensity": float(p.intensity),
                                            "effective_debt_g": float(p.effective_debt_g)} for p in eng.new_timeline]
    return out


def charts(res: dict, demo: dict) -> None:
    agg = res["aggregates"]
    pols = list(agg)
    fig, axes = plt.subplots(1, 4, figsize=(13, 3.2))
    for ax, (key, title) in zip(axes, [("gross_emissions_g", "Gross emissions (g)"), ("total_debt_g", "Debt incurred (g)"),
                                      ("final_debt_g", "Final outstanding debt (g)"), ("deadline_misses", "Deadline misses")]):
        means = [agg[p][key]["mean"] for p in pols]
        stds = [agg[p][key]["std"] for p in pols]
        ax.bar([SHORT[p] for p in pols], means, yerr=stds, color=[COLORS[p] for p in pols], capsize=3, width=0.65)
        ax.set_title(title, fontsize=10.5, loc="left")
        ax.tick_params(axis="x", labelrotation=20, labelsize=8.5)
    fig.suptitle("Policy comparison — mean ± 1 s.d. over 10 seeds (SIMULATED)", x=0.01, ha="left", fontsize=11)
    fig.tight_layout()
    fig.savefig(OUT / "policy_comparison.png", dpi=200)
    plt.close(fig)

    tl = demo["_predictive_timeline"]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(9, 4.6), sharex=True, gridspec_kw={"height_ratios": [1.3, 1]})
    hours = [p["slot"] / 4 for p in tl]
    a1.plot(hours, [p["intensity"] for p in tl], color="#222", lw=1.8)
    a1.axhline(350, color="#d03b3b", ls="--", lw=1)
    a1.axhline(200, color="#1a9e5c", ls="--", lw=1)
    a1.fill_between(hours, 0, 700, where=[p["intensity"] <= 200 for p in tl], color="#1a9e5c", alpha=0.12, step="mid")
    a1.set_ylabel("gCO₂e/kWh")
    a1.set_ylim(0, 720)
    a1.set_title("Demo scenario: grid intensity (dashed: debt 350 / green 200) and effective carbon debt", loc="left", fontsize=10.5)
    a2.step(hours, [p["effective_debt_g"] for p in tl], where="post", color="#6c5ce7", lw=2)
    a2.fill_between(hours, [p["effective_debt_g"] for p in tl], step="post", color="#6c5ce7", alpha=0.15)
    a2.set_ylabel("Debt (g)")
    a2.set_xlabel("Simulated hour (UTC)")
    fig.tight_layout()
    fig.savefig(OUT / "scenario_timeline.png", dpi=200)
    plt.close(fig)

    if res.get("sweep"):
        pts = res["sweep"]["points"]
        fig, axes = plt.subplots(1, 3, figsize=(11, 3))
        for ax, key in zip(axes, ["gross_emissions_g", "final_debt_g", "deadline_misses"]):
            ax.plot([p["value"] for p in pts], [p["aggregates"][key]["mean"] for p in pts], marker="o", color=COLORS["debt_predictive"])
            ax.set_title(res["metric_labels"][key]["label"], fontsize=10, loc="left")
            ax.set_xlabel("Green threshold (gCO₂e/kWh)")
        fig.tight_layout()
        fig.savefig(OUT / "green_threshold_sweep.png", dpi=200)
        plt.close(fig)


def main() -> None:
    req = ExperimentRequest(name="Canonical comparison (docs)", seeds=list(range(1, 11)),
                            sweep_param="green_threshold", sweep_values=[150, 200, 250, 300])
    res = run_experiment(req)
    demo = scenario()
    (OUT / "experiment_results.json").write_text(json.dumps(
        {"request": req.model_dump(mode="json"), "aggregates": res["aggregates"],
         "comparisons_vs_fifo_pct": res["comparisons_vs_reference_pct"], "sweep": res["sweep"],
         "trace_summary": res["trace_summary"], "environment": res["environment"],
         "methodology": res["methodology"]}, indent=2))
    with (OUT / "experiment_runs.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["policy", "seed"] + METRIC_KEYS)
        for r in res["runs"]:
            w.writerow([r["policy"], r["seed"]] + [r["metrics"][k] for k in METRIC_KEYS])
    (OUT / "scenario_results.json").write_text(json.dumps(
        {k: v for k, v in demo.items() if k != "_predictive_timeline"}, indent=2))
    charts(res, demo)
    print("Wrote", ", ".join(sorted(p.name for p in OUT.iterdir())))
    for p, a in res["aggregates"].items():
        print(f"{p:16s}", {k: a[k]["mean"] for k in ("gross_emissions_g", "total_debt_g", "credits_applied_g",
                                                    "final_debt_g", "peak_debt_g", "deadline_misses", "avg_delay_min",
                                                    "energy_kwh", "throttle_actions", "decision_overhead_us")})
    for p in ("fifo", "threshold", "debt_reactive", "debt_predictive"):
        m = demo[p]
        print("scenario", f"{p:16s}", {k: m[k] for k in ("gross_emissions_g", "total_debt_g", "credits_applied_g",
                                                         "final_debt_g", "peak_debt_g", "deadline_misses", "avg_delay_min")})


if __name__ == "__main__":
    main()
