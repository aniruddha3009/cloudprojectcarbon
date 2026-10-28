"""Background experiment execution, persistence and export."""

from __future__ import annotations

import csv
import io
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from ..core.experiment import ExperimentRequest, run_experiment
from ..core.metrics import METRIC_KEYS
from ..db import Database
from ..models import ExperimentRow

log = logging.getLogger("carbon_debt.experiments")


class ExperimentService:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._worker_lock = threading.Lock()  # one experiment at a time keeps the demo laptop responsive

    def submit(self, req: ExperimentRequest, background: bool = True) -> dict[str, Any]:
        exp_id = str(uuid.uuid4())
        with self.db.session() as s:
            s.add(ExperimentRow(id=exp_id, name=req.name, status="queued", progress=0.0,
                                config=req.model_dump(mode="json")))
        if background:
            threading.Thread(target=self._run, args=(exp_id, req), name=f"exp-{exp_id[:8]}", daemon=True).start()
        else:
            self._run(exp_id, req)
        return self.get(exp_id, include_results=not background)

    def _set(self, exp_id: str, **values: Any) -> None:
        with self.db.session() as s:
            row = s.get(ExperimentRow, exp_id)
            if row is not None:
                for k, v in values.items():
                    setattr(row, k, v)

    def _run(self, exp_id: str, req: ExperimentRequest) -> None:
        with self._worker_lock:
            self._set(exp_id, status="running")
            started = time.perf_counter()
            last = [0.0]

            def progress(p: float) -> None:
                if p - last[0] >= 0.04 or p >= 1.0:
                    last[0] = p
                    self._set(exp_id, progress=round(p, 3))

            try:
                results = run_experiment(req, progress)
                self._set(exp_id, status="completed", progress=1.0, results=results,
                          duration_ms=round((time.perf_counter() - started) * 1000, 1))
                log.info("experiment completed", extra={"experiment_id": exp_id})
            except Exception as exc:  # surfaced to the UI, never swallowed
                log.exception("experiment failed")
                self._set(exp_id, status="failed", error=f"{exc.__class__.__name__}: {exc}",
                          duration_ms=round((time.perf_counter() - started) * 1000, 1))

    @staticmethod
    def _dict(row: ExperimentRow, include_results: bool) -> dict[str, Any]:
        data = {"id": row.id, "name": row.name, "status": row.status, "progress": row.progress,
                "config": row.config, "error": row.error, "duration_ms": row.duration_ms,
                "created_at": row.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if row.created_at else None}
        if include_results:
            data["results"] = row.results
        return data

    def get(self, exp_id: str, include_results: bool = True) -> dict[str, Any]:
        with self.db.session() as s:
            row = s.get(ExperimentRow, exp_id)
            if row is None:
                raise LookupError(f"experiment {exp_id} not found")
            return self._dict(row, include_results)

    def list(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.db.session() as s:
            rows = s.scalars(select(ExperimentRow).order_by(ExperimentRow.created_at.desc()).limit(limit)).all()
            return [self._dict(r, False) for r in rows]

    def delete(self, exp_id: str) -> None:
        with self.db.session() as s:
            row = s.get(ExperimentRow, exp_id)
            if row is None:
                raise LookupError(f"experiment {exp_id} not found")
            if row.status in ("queued", "running"):
                raise ValueError("cannot delete a running experiment")
            s.delete(row)

    def export_csv(self, exp_id: str) -> str:
        exp = self.get(exp_id)
        results = exp.get("results")
        if not results:
            raise ValueError("experiment has no results yet")
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["experiment_id", "row_type", "policy", "seed", "stat"] + METRIC_KEYS)
        for run in results["runs"]:
            writer.writerow([exp_id, "run", run["policy"], run["seed"], "value"] + [run["metrics"][k] for k in METRIC_KEYS])
        for policy, agg in results["aggregates"].items():
            for stat in ("mean", "std", "min", "max"):
                writer.writerow([exp_id, "aggregate", policy, "all", stat] + [agg[k][stat] for k in METRIC_KEYS])
        if results.get("sweep"):
            sweep = results["sweep"]
            for point in sweep["points"]:
                writer.writerow([exp_id, f"sweep:{sweep['param']}={point['value']}", sweep["policy"], "all", "mean"]
                                + [point["aggregates"][k]["mean"] for k in METRIC_KEYS])
        return buf.getvalue()

    def export_report(self, exp_id: str) -> dict[str, Any]:
        exp = self.get(exp_id)
        results = exp.get("results")
        if not results:
            raise ValueError("experiment has no results yet")
        return {
            "experiment_id": exp_id, "name": exp["name"], "created_at": exp["created_at"],
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "duration_ms": exp["duration_ms"], "config": exp["config"],
            "reference_policy": results["reference_policy"], "aggregates": results["aggregates"],
            "comparisons_vs_reference_pct": results["comparisons_vs_reference_pct"],
            "sweep": results.get("sweep"), "trace_summary": results["trace_summary"],
            "environment": results["environment"], "methodology": results["methodology"],
            "data_label": "SIMULATED — deterministic replay; not hardware-measured",
        }
