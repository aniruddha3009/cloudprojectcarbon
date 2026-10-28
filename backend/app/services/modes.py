"""Exactly two operating modes: Simulation and Live.

Each mode has its own service and database, so simulated records and live records can never mix.
The active mode is remembered in the simulation database (settings key ``app_mode``).
"""

from __future__ import annotations

from typing import Literal

from ..models import SettingRow
from .live import LiveService
from .simulation import SimulationService

Mode = Literal["simulation", "live"]


class ModeManager:
    def __init__(self, simulation: SimulationService, live: LiveService) -> None:
        self.simulation = simulation
        self.live = live

    def get(self) -> Mode:
        with self.simulation.db.session() as s:
            row = s.get(SettingRow, "app_mode")
            return "live" if row is not None and row.value == "live" else "simulation"

    def set(self, mode: Mode) -> Mode:
        if mode not in ("simulation", "live"):
            raise ValueError("mode must be 'simulation' or 'live'")
        if mode == "simulation":
            self.live.stop_monitoring()  # leaving Live mode stops telemetry and managed workloads
        with self.simulation.db.session() as s:
            row = s.get(SettingRow, "app_mode")
            if row is None:
                s.add(SettingRow(key="app_mode", value=mode))
            else:
                row.value = mode
        return mode

    def active(self) -> SimulationService:
        return self.live if self.get() == "live" else self.simulation
