"""Demo workloads and deterministic workload traces.

All power figures are *declared estimates* for a simulated cluster node
(e.g. a GPU inference node ≈ 1.5 kW) — they are labelled ESTIMATED everywhere.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from decimal import Decimal

from .carbon_curve import SLOT_MINUTES, SLOTS_PER_HOUR
from .engine import SimJob

SCENARIO_START_SLOT = 6 * SLOTS_PER_HOUR      # 06:00
SCENARIO_END_SLOT = 16 * SLOTS_PER_HOUR       # 16:00


def hm(text: str) -> int:
    """'07:15' → slot index; 'D+1 06:00' supported for next-day times."""
    day = 0
    if text.startswith("D+"):
        day_part, text = text.split(" ", 1)
        day = int(day_part[2:])
    h, m = (int(x) for x in text.split(":"))
    if m % SLOT_MINUTES:
        raise ValueError("times must align to 15-minute slots")
    return day * 24 * SLOTS_PER_HOUR + h * SLOTS_PER_HOUR + m // SLOT_MINUTES


@dataclass(frozen=True)
class DemoJob:
    name: str
    workload: str
    job_class: str
    priority: int
    power_w: int
    runtime_min: int
    arrival: str
    deadline: str
    story: str


DEMO_JOBS: list[DemoJob] = [
    DemoJob("Log compaction", "observability", "background", 4, 600, 120, "06:00", "09:30",
            "Starts before the emergency while the grid is below the debt threshold; later throttled and paused "
            "by the debt controller without missing its deadline."),
    DemoJob("Hospital triage model failover", "triage-ai", "emergency", 1, 1500, 60, "06:45", "08:00",
            "Emergency: must run immediately during the high-carbon morning peak → creates carbon debt."),
    DemoJob("Billing reconciliation", "billing", "normal", 2, 800, 45, "07:00", "08:30",
            "Tight deadline: cannot wait for a green window; deadline protection forces it to run."),
    DemoJob("Nightly ETL backfill", "data-platform", "normal", 3, 1000, 60, "07:00", "16:00",
            "Flexible: deferred into the solar green window as repayment work."),
    DemoJob("Hyper-parameter sweep", "ml-research", "background", 5, 1200, 90, "07:00", "20:00",
            "Low nominal priority but highest repayment value — priority inversion runs it first in the green window."),
    DemoJob("Flood-alert ensemble recompute", "flood-alert", "emergency", 1, 1200, 45, "07:15", "08:30",
            "Second emergency during the peak; adds more debt and pushes the controller into a higher band."),
    DemoJob("Quarterly report rendering", "reporting", "normal", 3, 400, 30, "08:00", "10:30",
            "No green window before its deadline: moved to the least-carbon feasible slot instead."),
    DemoJob("Search index rebuild", "search", "background", 4, 700, 60, "09:00", "D+1 06:00",
            "Arrives mid-morning; deferred to the green window."),
]


def demo_sim_jobs(id_prefix: str = "J-", start_index: int = 1) -> list[SimJob]:
    jobs = []
    for i, d in enumerate(DEMO_JOBS):
        jobs.append(
            SimJob(
                id=f"{id_prefix}{start_index + i:04d}",
                name=d.name,
                workload=d.workload,
                job_class=d.job_class,
                priority=d.priority,
                power_w=Decimal(d.power_w),
                runtime_min=d.runtime_min,
                arrival_slot=hm(d.arrival),
                deadline_slot=hm(d.deadline),
            )
        )
    return jobs


@dataclass(frozen=True)
class TraceSpec:
    seed: int = 1
    emergency: int = 4
    normal: int = 18
    background: int = 14
    arrival_window_slots: int = 88  # arrivals between 00:00 and 22:00


def generate_trace(spec: TraceSpec) -> list[SimJob]:
    """Seeded synthetic trace; identical seeds give identical traces on every platform."""
    rng = random.Random(spec.seed)
    raw: list[tuple[int, str, int, int, int, int, int | None]] = []
    for _ in range(spec.emergency):
        arrival = rng.randrange(0, spec.arrival_window_slots)
        runtime = rng.choice([30, 45, 60, 90])
        need = math.ceil(runtime / SLOT_MINUTES)
        raw.append((arrival, "emergency", 1, rng.choice([800, 1000, 1200, 1500, 2000]), runtime, arrival + need + 2, None))
    for _ in range(spec.normal):
        arrival = rng.randrange(0, spec.arrival_window_slots)
        runtime = rng.choice([15, 30, 45, 60, 90, 120])
        need = math.ceil(runtime / SLOT_MINUTES)
        slack = rng.randrange(1 * SLOTS_PER_HOUR, 10 * SLOTS_PER_HOUR)
        raw.append((arrival, "normal", rng.choice([2, 3]), rng.randrange(300, 1300, 100), runtime, arrival + need + slack, None))
    for _ in range(spec.background):
        arrival = rng.randrange(0, spec.arrival_window_slots)
        runtime = rng.choice([60, 90, 120, 180, 240])
        need = math.ceil(runtime / SLOT_MINUTES)
        slack = rng.randrange(8 * SLOTS_PER_HOUR, 24 * SLOTS_PER_HOUR)
        raw.append((arrival, "background", rng.choice([4, 5]), rng.randrange(400, 1600, 100), runtime,
                    arrival + need + slack, 20 * 60))
    raw.sort(key=lambda r: (r[0], r[1]))
    names = {"emergency": "Incident response", "normal": "Batch task", "background": "Background task"}
    workloads = {"emergency": ["triage-ai", "flood-alert", "fraud-guard"],
                 "normal": ["billing", "data-platform", "reporting"],
                 "background": ["ml-research", "search", "observability"]}
    jobs = []
    for i, (arrival, cls, prio, power, runtime, deadline, max_wait) in enumerate(raw, start=1):
        jobs.append(
            SimJob(
                id=f"T{i:03d}",
                name=f"{names[cls]} {i}",
                workload=workloads[cls][i % 3],
                job_class=cls,
                priority=prio,
                power_w=Decimal(power),
                runtime_min=runtime,
                arrival_slot=arrival,
                deadline_slot=deadline,
                max_wait_min=max_wait,
            )
        )
    return jobs
