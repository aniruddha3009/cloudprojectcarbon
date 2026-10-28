"""Live laptop telemetry: Windows processes, CPU/memory, and the CPU-package energy meter.

What is measured, and how:
  * Processes   psutil (read-only). Only name, PID, CPU %, memory, status and start time are read —
                never command lines, window titles, files or user data. Nothing is paused or killed.
  * CPU/memory  psutil system counters.
  * Energy      Windows "Energy Meter" performance counter, instance ``rapl_package0_pkg``: Intel RAPL
                cumulative CPU-package energy in picowatt-hours, read through the built-in PDH API
                (ctypes, no admin rights). On Linux the powercap RAPL file is used if readable.
                Package energy covers the whole CPU package (all programs), not one process; a managed
                job's share is attributed by its CPU time (see live.py). Battery discharge is NOT used:
                it is whole-laptop power and only exists on battery.
"""

from __future__ import annotations

import ctypes
import logging
import os
import platform
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

log = logging.getLogger("carbon_debt.system_monitor")

PWH_TO_J = 3.6e-9  # 1 picowatt-hour = 3.6e-9 joules
RAPL_LINUX = Path("/sys/class/powercap/intel-rapl:0/energy_uj")


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------------------- energy meter
class _PdhRaw(ctypes.Structure):
    _fields_ = [("CStatus", ctypes.c_ulong), ("TimeStamp", ctypes.c_ulong * 2),
                ("FirstValue", ctypes.c_longlong), ("SecondValue", ctypes.c_longlong), ("MultiCount", ctypes.c_ulong)]


class EnergyMeter:
    """Cumulative CPU-package energy in joules, or unavailable with a reason."""

    WIN_COUNTER = r"\Energy Meter(rapl_package0_pkg)\Energy"

    def __init__(self) -> None:
        self.available = False
        self.source = "none"
        self.message = ""
        self._query = ctypes.c_void_p()
        self._counter = ctypes.c_void_p()
        self._open()

    def _open(self) -> None:
        system = platform.system()
        if system == "Windows":
            try:
                pdh = ctypes.WinDLL("pdh.dll")
                if pdh.PdhOpenQueryW(None, None, ctypes.byref(self._query)) != 0:
                    raise OSError("PdhOpenQuery failed")
                if pdh.PdhAddEnglishCounterW(self._query, ctypes.c_wchar_p(self.WIN_COUNTER), None, ctypes.byref(self._counter)) != 0:
                    raise OSError("this PC does not expose the Windows Energy Meter (RAPL) counter")
                self._pdh = pdh
                if self.read_joules() is None:
                    raise OSError("Energy Meter counter returned no data")
                self.available, self.source = True, "Windows Energy Meter (Intel RAPL, CPU package)"
                self.message = "Measured CPU-package energy from the Windows Energy Meter counter (rapl_package0_pkg)."
            except Exception as exc:  # unsupported hardware/driver
                self.message = f"Energy meter unavailable: {exc}. Energy will be estimated from CPU time."
        elif system == "Linux" and RAPL_LINUX.exists():
            try:
                int(RAPL_LINUX.read_text().strip())
                self.available, self.source = True, "Linux powercap (Intel RAPL, CPU package)"
                self.message = "Measured CPU-package energy from /sys/class/powercap."
            except PermissionError:
                self.message = "RAPL exists but is not readable without root. Energy will be estimated from CPU time."
            except (OSError, ValueError) as exc:  # e.g. inside a cloud container
                self.message = f"Energy meter unavailable: {exc}. Energy will be estimated from CPU time."
        else:
            self.message = f"No supported energy meter on {system}. Energy will be estimated from CPU time."

    def read_joules(self) -> float | None:
        try:
            if platform.system() == "Windows":
                if self._pdh.PdhCollectQueryData(self._query) != 0:
                    return None
                raw = _PdhRaw()
                ctype = ctypes.c_ulong()
                if self._pdh.PdhGetRawCounterValue(self._counter, ctypes.byref(ctype), ctypes.byref(raw)) != 0 or raw.CStatus > 1:
                    return None
                return raw.FirstValue * PWH_TO_J
            return int(RAPL_LINUX.read_text().strip()) / 1e6
        except Exception:
            return None


# ------------------------------------------------------------------- telemetry
@dataclass
class _Window:
    package_j: float = 0.0
    busy_cpu_s: float = 0.0
    seconds: float = 0.0


class SystemMonitor:
    """Background sampler (every ~2.5 s while Live monitoring is on)."""

    def __init__(self, interval_s: float) -> None:
        self.interval_s = interval_s
        self.meter = EnergyMeter()
        self._lock = threading.Lock()
        self._procs: dict[int, dict[str, Any]] = {}
        self._snapshot: dict[str, Any] = {"processes": [], "refreshed_at": None}
        self._history: deque[dict[str, Any]] = deque(maxlen=240)
        self._window = _Window()
        self._last_energy: float | None = None
        self._last_busy: float | None = None
        self._last_t: float | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.ncpu = psutil.cpu_count(logical=True) or 1
        self.own_pid = os.getpid()

    # lifecycle
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            if not self._stop.is_set():
                return
            self._thread.join(timeout=5)  # a stop is in progress: let it finish, then restart
        self._stop.clear()
        psutil.cpu_percent(None)
        self._thread = threading.Thread(target=self._run, name="system-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.sample()
            except Exception:  # never let telemetry kill the app
                log.exception("telemetry sample failed")
            self._stop.wait(self.interval_s)

    # sampling
    @staticmethod
    def _busy_seconds() -> float:
        t = psutil.cpu_times()
        return sum(t) - getattr(t, "idle", 0.0) - getattr(t, "iowait", 0.0)

    def sample(self) -> None:
        """One refresh. Kept fast on Windows (~1 s for ~300 processes): memory and CPU times are read in
        one pass, start times are cached per PID, and the costly status lookup runs every 6th sample."""
        now = time.monotonic()
        energy = self.meter.read_joules() if self.meter.available else None
        busy = self._busy_seconds()
        self._samples = getattr(self, "_samples", 0) + 1
        refresh_status = self._samples % 6 == 1
        prev_t = self._last_t
        rows = []
        seen = set()
        for p in psutil.process_iter(["pid", "name", "memory_info", "cpu_times"]):
            pid = p.info["pid"]
            if pid == 0:  # "System Idle Process" is not a program
                continue
            seen.add(pid)
            cache = self._procs.get(pid)
            if cache is None or cache.get("name") != p.info.get("name"):  # new process (or PID reused)
                try:
                    created = p.create_time()
                except (psutil.Error, OSError):
                    created = None
                cache = self._procs[pid] = {"name": p.info.get("name"), "created": created, "cpu": None, "status": None}
                refresh_this = True
            else:
                refresh_this = refresh_status
            if refresh_this:
                try:
                    cache["status"] = p.status()
                except (psutil.Error, OSError):
                    pass
            times, mem = p.info.get("cpu_times"), p.info.get("memory_info")
            total = (times.user + times.system) if times else None
            cpu = None
            if total is not None and cache["cpu"] is not None and prev_t is not None and now > prev_t:
                cpu = max(0.0, (total - cache["cpu"]) / (now - prev_t) / self.ncpu * 100)
            cache["cpu"] = total
            created = cache["created"]
            rows.append({
                "pid": pid,
                "name": p.info.get("name") or "(unknown)",
                "cpu_percent": None if times is None else round(cpu or 0.0, 1),
                "memory_mb": None if mem is None else round(mem.rss / 1_048_576, 1),
                "status": cache["status"],
                "started_at": datetime.fromtimestamp(created, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if created else None,
                "is_app_backend": pid == self.own_pid,
            })
        for gone in set(self._procs) - seen:  # processes that exited since the last refresh
            self._procs.pop(gone, None)
        vm = psutil.virtual_memory()
        system_cpu = psutil.cpu_percent(None)
        package_w = None
        with self._lock:
            if self._last_t is not None:
                dt = now - self._last_t
                self._window.seconds += dt
                self._window.busy_cpu_s += max(0.0, busy - (self._last_busy or busy))
                if energy is not None and self._last_energy is not None and energy >= self._last_energy:
                    de = energy - self._last_energy
                    self._window.package_j += de
                    package_w = de / dt if dt > 0 else None
            self._last_t, self._last_busy, self._last_energy = now, busy, energy
            refreshed = _utc()
            self._snapshot = {
                "refreshed_at": refreshed,
                "processes": rows,
                "process_count": len(rows),
                "system": {
                    "cpu_percent": round(system_cpu, 1),
                    "memory_percent": round(vm.percent, 1),
                    "memory_used_gb": round((vm.total - vm.available) / 1_073_741_824, 2),
                    "memory_total_gb": round(vm.total / 1_073_741_824, 2),
                    "logical_cpus": self.ncpu,
                    "package_power_w": None if package_w is None else round(package_w, 2),
                },
            }
            self._history.append({"t": refreshed, "cpu_percent": round(system_cpu, 1), "memory_percent": round(vm.percent, 1),
                                  "package_power_w": None if package_w is None else round(package_w, 2)})

    def consume_window(self) -> _Window:
        """Package energy and total busy CPU time since the previous call (one accounting slot)."""
        with self._lock:
            w, self._window = self._window, _Window()
            return w

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {**self._snapshot, "history": list(self._history), "running": self.running,
                    "interval_s": self.interval_s,
                    "energy_meter": {"available": self.meter.available, "source": self.meter.source,
                                     "message": self.meter.message}}
