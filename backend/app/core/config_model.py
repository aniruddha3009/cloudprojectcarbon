"""Controller / simulation configuration (validated, versionable, JSON-serialisable)."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PolicyName = Literal["fifo", "threshold", "debt_reactive", "debt_predictive"]
ProfileName = Literal["solar_midday", "windy_night", "dirty_flat"]
CarbonSource = Literal["simulated", "live_snapshot"]


class IntensityOverride(BaseModel):
    """Operator-injected grid event: force an intensity for a window of the sim day."""

    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    start_hour: float = Field(default=11.0, ge=0, le=72)
    end_hour: float = Field(default=12.0, ge=0, le=72)
    intensity: Decimal = Field(default=Decimal("650"), ge=0, le=2000)

    @model_validator(mode="after")
    def _order(self) -> "IntensityOverride":
        if self.end_hour <= self.start_hour:
            raise ValueError("override end_hour must be after start_hour")
        return self


class GridEvent(BaseModel):
    """Presenter-set simulated grid level ("Switch to green/coal-heavy energy") for slots [from_slot, to_slot).

    Events are kept after they end so the intensity history of past slots never changes.
    """

    model_config = ConfigDict(extra="forbid")
    from_slot: int = Field(ge=0)
    to_slot: int = Field(ge=1)
    intensity: Decimal = Field(ge=0, le=2000)
    label: str = Field(default="custom", max_length=20)

    @model_validator(mode="after")
    def _order(self) -> "GridEvent":
        if self.to_slot <= self.from_slot:
            raise ValueError("grid event must end after it starts")
        return self


class ControllerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy: PolicyName = "debt_predictive"

    # Intensity thresholds (gCO2e/kWh)
    debt_intensity_threshold: Decimal = Field(default=Decimal("350"), ge=0, le=2000,
        description="I_threshold: execution above this intensity incurs policy-defined debt")
    green_threshold: Decimal = Field(default=Decimal("200"), ge=0, le=2000,
        description="Slots at or below this intensity form green windows")

    # Debt bands (gCO2e) that drive progressive throttling
    debt_soft_g: Decimal = Field(default=Decimal("100"), ge=0)
    debt_hard_g: Decimal = Field(default=Decimal("400"), ge=0)
    debt_critical_g: Decimal = Field(default=Decimal("800"), ge=0)

    # Cluster model
    workers: int = Field(default=4, ge=1, le=64)
    emergency_reserve: int = Field(default=1, ge=0, le=16)
    static_power_fraction: Decimal = Field(default=Decimal("0.30"), ge=0, le=Decimal("0.9"))

    # Planner
    min_deferral_savings_g: Decimal = Field(default=Decimal("5"), ge=0,
        description="Predictive controller will not delay work for less than this expected saving")
    planning_horizon_slots: int = Field(default=96, ge=4, le=288)
    proactive_throttling: bool = True

    # Carbon curve
    carbon_source: CarbonSource = "simulated"
    profile: ProfileName = "solar_midday"
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    noise_pct: Decimal = Field(default=Decimal("3"), ge=0, le=25)
    override: IntensityOverride = Field(default_factory=IntensityOverride)
    grid_events: list[GridEvent] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _consistency(self) -> "ControllerConfig":
        if self.green_threshold > self.debt_intensity_threshold:
            raise ValueError("green_threshold must be ≤ debt_intensity_threshold")
        if not (self.debt_soft_g <= self.debt_hard_g <= self.debt_critical_g):
            raise ValueError("debt bands must satisfy soft ≤ hard ≤ critical")
        if self.emergency_reserve >= self.workers:
            raise ValueError("emergency_reserve must be smaller than workers")
        return self
