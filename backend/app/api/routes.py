"""REST API (all under /api; OpenAPI docs at /docs)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text

from ..config import Settings
from ..core.experiment import ExperimentRequest
from ..schemas import (AdvanceRequest, AutoplayRequest, GridRequest, JobAction, JobCreate, ModeRequest, MonitoringRequest,
                       ResetRequest, ScenarioRequest, SettingsPatch, TamperRequest)
from ..services.experiments import ExperimentService
from ..services.live import LiveService
from ..services.modes import ModeManager
from ..services.simulation import SimulationService
from . import deps

router = APIRouter(prefix="/api")
admin = [Depends(deps.require_admin)]


# --------------------------------------------------------------------- system
@router.get("/health", tags=["system"])
def health(sim: SimulationService = Depends(deps.sim), settings: Settings = Depends(deps.settings)) -> dict[str, Any]:
    db_ok = True
    try:
        with sim.db.session() as s:
            s.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": "ok" if db_ok else "unavailable",
            "environment": settings.environment, "database_kind": sim.db.url.split(":", 1)[0],
            "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "admin_token_required": bool(settings.admin_token)}


@router.get("/state", tags=["system"], summary="Current system state for the dashboard")
def state(sim: SimulationService = Depends(deps.sim)) -> dict[str, Any]:
    return sim.state()


# ----------------------------------------------------------------- simulation
@router.post("/sim/advance", tags=["simulation"], dependencies=admin)
def advance(body: AdvanceRequest, sim: SimulationService = Depends(deps.sim)) -> dict[str, Any]:
    return sim.tick(body.slots)


@router.post("/sim/autoplay", tags=["simulation"], dependencies=admin)
def autoplay(body: AutoplayRequest, sim: SimulationService = Depends(deps.sim)) -> dict[str, Any]:
    return sim.set_autoplay(body.enabled, body.speed_ms)


@router.post("/scenario/run", tags=["scenario"], dependencies=admin,
             summary="Run Emergency-to-Green Repayment Scenario (resets demo data)")
def run_scenario(body: ScenarioRequest, sim: SimulationService = Depends(deps.sim)) -> dict[str, Any]:
    return sim.run_scenario(body.mode, body.speed_ms)


@router.get("/scenario/status", tags=["scenario"])
def scenario_status(sim: SimulationService = Depends(deps.sim)) -> dict[str, Any]:
    return sim.scenario_status()


@router.post("/demo/load", tags=["scenario"], dependencies=admin, summary="Load demo workloads (resets demo data)")
def load_demo(sim: SimulationService = Depends(deps.sim)) -> dict[str, Any]:
    return {"loaded": sim.load_demo()}


@router.post("/demo/samples", tags=["scenario"], dependencies=admin,
             summary="Load four sample processes arriving now (resets demo data)")
def load_samples(sim: SimulationService = Depends(deps.sim)) -> dict[str, Any]:
    return {"loaded": sim.load_samples()}


@router.post("/sim/grid", tags=["simulation"], dependencies=admin,
             summary="Set the simulated grid: green, coal-heavy, a custom value, or the normal daily pattern")
def set_grid(body: GridRequest, sim: SimulationService = Depends(deps.sim)) -> dict[str, Any]:
    return sim.set_grid(body.preset, body.intensity, body.hours)


@router.post("/demo/reset", tags=["scenario"], dependencies=admin)
def reset_demo(body: ResetRequest, sim: SimulationService = Depends(deps.sim)) -> dict[str, Any]:
    sim.reset()
    return {"reset": True}


@router.get("/timeline", tags=["simulation"])
def timeline(sim: SimulationService = Depends(deps.sim)) -> dict[str, Any]:
    return sim.timeline()


@router.get("/gantt", tags=["simulation"])
def gantt(sim: SimulationService = Depends(deps.sim)) -> dict[str, Any]:
    return sim.gantt()


# ----------------------------------------------------------------------- jobs
@router.get("/jobs", tags=["jobs"])
def list_jobs(state: str | None = None, job_class: str | None = None, q: str | None = Query(None, max_length=80),
              sim: SimulationService = Depends(deps.sim)) -> list[dict[str, Any]]:
    return sim.list_jobs(state, job_class, q)


@router.post("/jobs", tags=["jobs"], status_code=201, dependencies=admin)
def create_job(body: JobCreate, response: Response, sim: SimulationService = Depends(deps.sim)) -> dict[str, Any]:
    result = sim.create_job(body.model_dump())
    if result["duplicate"]:
        response.status_code = 200
    return result


@router.get("/jobs/{job_id}", tags=["jobs"])
def job_detail(job_id: str, sim: SimulationService = Depends(deps.sim)) -> dict[str, Any]:
    return sim.job_detail(job_id)


@router.get("/jobs/{job_id}/receipt", tags=["jobs"])
def job_receipt(job_id: str, sim: SimulationService = Depends(deps.sim)) -> dict[str, Any]:
    return sim.receipt(job_id)


@router.post("/jobs/{job_id}/actions", tags=["jobs"], dependencies=admin)
def job_action(job_id: str, body: JobAction, sim: SimulationService = Depends(deps.sim)) -> dict[str, Any]:
    return sim.job_action(job_id, body.action, body.hold_minutes)


@router.get("/decisions", tags=["controller"])
def decisions(limit: int = Query(100, ge=1, le=1000), job_id: str | None = None, action: str | None = None,
              sim: SimulationService = Depends(deps.sim)) -> list[dict[str, Any]]:
    return sim.decisions(limit, job_id, action)


# ------------------------------------------------------------ carbon/controller
@router.get("/carbon/curve", tags=["carbon"])
def carbon_curve(sim: SimulationService = Depends(deps.sim)) -> dict[str, Any]:
    return sim.carbon_curve()


@router.get("/controller", tags=["controller"])
def controller(sim: SimulationService = Depends(deps.sim)) -> dict[str, Any]:
    return sim.controller_view()


@router.put("/controller/settings", tags=["controller"], dependencies=admin)
def update_settings(body: SettingsPatch, sim: SimulationService = Depends(deps.sim)) -> dict[str, Any]:
    return sim.update_settings(body.changes())


# --------------------------------------------------------------------- ledger
@router.get("/ledger", tags=["ledger"])
def ledger(event_type: str | None = None, job_id: str | None = None,
           sim: SimulationService = Depends(deps.sim)) -> list[dict[str, Any]]:
    return sim.ledger(event_type, job_id)


@router.get("/ledger/verify", tags=["ledger"])
def verify_ledger(expected_head: str | None = Query(None, pattern="^[0-9a-f]{64}$"),
                  sim: SimulationService = Depends(deps.sim)) -> dict[str, Any]:
    return sim.verify_ledger(expected_head)


@router.post("/ledger/tamper-demo", tags=["ledger"], summary="Tamper with an in-memory COPY and show detection")
def tamper_demo(body: TamperRequest, sim: SimulationService = Depends(deps.sim)) -> dict[str, Any]:
    return sim.tamper_demo(body.seq, body.field)


@router.get("/ledger/export.csv", tags=["ledger"])
def ledger_csv(sim: SimulationService = Depends(deps.sim)) -> Response:
    import csv
    import io

    rows = sim.ledger()
    buf = io.StringIO()
    cols = ["seq", "event_id", "event_type", "job_id", "sim_time", "recorded_at", "energy_kwh", "intensity_actual",
            "intensity_baseline", "amount_g", "balance_before_g", "balance_after_g", "reference_event_id",
            "idem_key", "prev_hash", "hash"]
    writer = csv.writer(buf)
    writer.writerow(cols)
    for r in rows:
        writer.writerow([r[c] for c in cols])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=carbon_debt_ledger.csv"})


@router.get("/stats/workloads", tags=["ledger"])
def workload_stats(sim: SimulationService = Depends(deps.sim)) -> list[dict[str, Any]]:
    return sim.workload_stats()


# ---------------------------------------------------------------- experiments
@router.post("/experiments", tags=["experiments"], status_code=202, dependencies=admin)
def run_experiment(body: ExperimentRequest, exp: ExperimentService = Depends(deps.experiments)) -> dict[str, Any]:
    return exp.submit(body)


@router.get("/experiments", tags=["experiments"])
def list_experiments(exp: ExperimentService = Depends(deps.experiments)) -> list[dict[str, Any]]:
    return exp.list()


@router.get("/experiments/defaults", tags=["experiments"])
def experiment_defaults() -> dict[str, Any]:
    return ExperimentRequest().model_dump(mode="json")


@router.get("/experiments/{exp_id}", tags=["experiments"])
def get_experiment(exp_id: str, exp: ExperimentService = Depends(deps.experiments)) -> dict[str, Any]:
    return exp.get(exp_id)


@router.delete("/experiments/{exp_id}", tags=["experiments"], dependencies=admin, status_code=204)
def delete_experiment(exp_id: str, exp: ExperimentService = Depends(deps.experiments)) -> Response:
    try:
        exp.delete(exp_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return Response(status_code=204)


@router.get("/experiments/{exp_id}/export.csv", tags=["experiments"])
def export_csv(exp_id: str, exp: ExperimentService = Depends(deps.experiments)) -> Response:
    try:
        content = exp.export_csv(exp_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return Response(content, media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=experiment_{exp_id[:8]}.csv"})


@router.get("/experiments/{exp_id}/report.json", tags=["experiments"])
def export_report(exp_id: str, exp: ExperimentService = Depends(deps.experiments)) -> Response:
    import json

    try:
        report = exp.export_report(exp_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return Response(json.dumps(report, indent=2), media_type="application/json",
                    headers={"Content-Disposition": f"attachment; filename=experiment_{exp_id[:8]}_report.json"})


# ----------------------------------------------------------------------- mode
@router.get("/mode", tags=["mode"])
def get_mode(modes: ModeManager = Depends(deps.modes)) -> dict[str, Any]:
    return {"mode": modes.get(), "modes": ["simulation", "live"]}


@router.put("/mode", tags=["mode"], dependencies=admin)
def set_mode(body: ModeRequest, modes: ModeManager = Depends(deps.modes)) -> dict[str, Any]:
    return {"mode": modes.set(body.mode)}


# ----------------------------------------------------------------------- live
@router.post("/live/monitoring", tags=["live"], dependencies=admin, summary="Start or stop Live monitoring")
def live_monitoring(body: MonitoringRequest, modes: ModeManager = Depends(deps.modes)) -> dict[str, Any]:
    if body.enabled and modes.get() != "live":
        raise HTTPException(409, "Switch to Live mode before starting monitoring.")
    return modes.live.set_autoplay(body.enabled)


@router.get("/live/status", tags=["live"], summary="Processes, CPU/memory, energy meter, grid feed, managed workloads")
def live_status(live: LiveService = Depends(deps.live)) -> dict[str, Any]:
    return live.live_status()


@router.post("/live/grid/refresh", tags=["live"], dependencies=admin, summary="Fetch the grid reading now (rate-limited)")
def live_grid_refresh(live: LiveService = Depends(deps.live)) -> dict[str, Any]:
    feed = live.feed
    last = feed.last_attempt
    if last is not None and (datetime.now(timezone.utc) - last).total_seconds() < 60:
        raise HTTPException(429, "Please wait a minute between manual refreshes (free keys allow 100 calls per day).")
    feed.fetch_latest()
    return feed.status()


# ------------------------------------------------------------------ telemetry
@router.get("/telemetry/status", tags=["telemetry"], summary="Where every number comes from in the active mode")
def telemetry_status(modes: ModeManager = Depends(deps.modes), settings: Settings = Depends(deps.settings)) -> dict[str, Any]:
    live = modes.live
    meter = live.monitor.meter
    return {
        "mode": modes.get(),
        "simulation": {
            "grid": "SIMULATED: deterministic seeded curve (no internet or API key needed)",
            "energy": "ESTIMATED: declared job power × runtime (static/dynamic throttle model)",
        },
        "live": {
            "grid": live.feed.status(),
            "energy": {
                "meter_available": meter.available, "meter_source": meter.source, "message": meter.message,
                "method": ("MEASURED CPU-package energy per slot × the job's share of busy CPU time"
                           if meter.available else
                           f"ESTIMATED: job CPU-seconds × {settings.live_core_watts} W per busy core"),
            },
            "processes": f"psutil, refreshed every {settings.process_poll_seconds} s while monitoring (read-only)",
            "slot_seconds": settings.live_slot_seconds,
            "job_duty": settings.live_job_duty,
        },
        "notes": [
            "CPU utilisation is not power. Energy comes from the energy meter (or the labelled estimate).",
            "Package energy covers the whole CPU; a job's share is attributed by its CPU time, which is itself an estimate.",
            "Gross emissions, policy debt and credits are separate quantities; credits never erase past emissions.",
            "Ordinary Windows programs are monitored only. The scheduler controls only workloads created in this app.",
        ],
    }
