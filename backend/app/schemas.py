"""Request models (validated at the API boundary)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _multiple_of_15(value: int | None) -> int | None:
    if value is not None and value % 15:
        raise ValueError("must be a multiple of 15 minutes (one scheduling slot)")
    return value


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    workload: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9][A-Za-z0-9 _.\-]*$")
    job_class: Literal["emergency", "normal", "background"]
    priority: int = Field(ge=1, le=5, description="1 = highest")
    power_w: Decimal = Field(default=Decimal("800"), ge=10, le=10000,
                             description="Declared average power (W). Simulation only; Live mode measures energy.")
    # Mode-specific rules (15-minute multiples in Simulation, 1–10 minutes in Live) are checked by the service.
    runtime_min: int = Field(ge=1, le=1440)
    arrival_offset_min: int = Field(default=0, ge=0, le=2880)
    deadline_offset_min: int = Field(ge=1, le=4320, description="Deadline measured from arrival (minutes)")
    max_wait_min: int | None = Field(default=None, ge=1, le=4320)
    simulate_failure: bool = False
    idempotency_key: str | None = Field(default=None, max_length=80, pattern=r"^[A-Za-z0-9_\-:.]+$")

    @model_validator(mode="after")
    def _deadline(self) -> "JobCreate":
        if self.deadline_offset_min < self.runtime_min:
            raise ValueError("deadline_offset_min must be at least runtime_min (deadline would be infeasible)")
        return self


class JobAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["run", "defer", "cancel"]
    hold_minutes: int | None = Field(default=None, ge=15, le=1440)

    @field_validator("hold_minutes")
    @classmethod
    def slot_aligned(cls, v: int | None) -> int | None:
        return _multiple_of_15(v)


class AdvanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slots: int = Field(default=1, ge=1, le=96)


class AutoplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    speed_ms: int | None = Field(default=None, ge=100, le=10000)


class ScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["animated", "instant"] = "animated"
    speed_ms: int | None = Field(default=None, ge=100, le=10000)


class ResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: Literal["RESET"] = Field(description='Must be the literal string "RESET"')


class SettingsPatch(BaseModel):
    """Partial update; merged with current settings and validated as a whole."""

    model_config = ConfigDict(extra="forbid")
    policy: str | None = None
    debt_intensity_threshold: Decimal | None = None
    green_threshold: Decimal | None = None
    debt_soft_g: Decimal | None = None
    debt_hard_g: Decimal | None = None
    debt_critical_g: Decimal | None = None
    workers: int | None = None
    emergency_reserve: int | None = None
    static_power_fraction: Decimal | None = None
    min_deferral_savings_g: Decimal | None = None
    planning_horizon_slots: int | None = None
    proactive_throttling: bool | None = None
    carbon_source: str | None = None
    profile: str | None = None
    seed: int | None = None
    noise_pct: Decimal | None = None
    override: dict[str, Any] | None = None

    def changes(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class TamperRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seq: int | None = Field(default=None, ge=1)
    field: Literal["amount_g", "intensity_baseline", "energy_kwh", "job_id", "delete", "reorder"] = "amount_g"


class GridRequest(BaseModel):
    """Simulation only: one-click grid level (green / coal-heavy), a custom value, or back to normal."""

    model_config = ConfigDict(extra="forbid")
    preset: Literal["green", "coal", "custom", "normal"]
    intensity: Decimal | None = Field(default=None, ge=0, le=2000)
    hours: float = Field(default=2, gt=0, le=72)


class ModeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["simulation", "live"]


class MonitoringRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
