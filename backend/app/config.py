"""Process configuration from environment variables / .env (never from the frontend)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env"),
                                      env_file_encoding="utf-8", extra="ignore")

    environment: str = Field(default="development", description="development | production")
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'carbon_debt.db').as_posix()}"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    admin_token: str | None = None
    log_level: str = "INFO"
    static_dir: str | None = None

    # Simulation execution
    kernel_ms: int = Field(default=20, ge=0, le=500, description="Real CPU proxy-kernel budget per job-slot at 100%")
    autoplay_default_ms: int = Field(default=800, ge=100, le=10000)
    max_jobs: int = Field(default=500, ge=10, le=10000)

    # Live mode (separate database so live records never mix with simulation records)
    live_database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'carbon_debt_live.db').as_posix()}"
    live_slot_seconds: int = Field(default=30, ge=10, le=900, description="Accounting slot length in Live mode")
    live_job_duty: float = Field(default=0.35, gt=0, le=0.8, description="Max share of one CPU core a managed job uses at 100%")
    live_max_jobs_running: int = Field(default=3, ge=1, le=8)
    live_core_watts: float = Field(default=12.0, gt=0, le=200,
                                   description="Fallback model: watts per fully busy core when no energy meter exists")
    process_poll_seconds: float = Field(default=2.5, ge=1.0, le=30.0)

    # India Energy Atlas (https://www.energymap.in/developer). Key stays on the server.
    india_energy_atlas_api_key: str | None = None
    india_energy_atlas_base_url: str = "https://api.energymap.in"
    india_energy_atlas_state: str | None = Field(default=None, description="State slug; requires a state-level plan")
    # Free Sandbox/Student keys allow 100 calls/day: 20-minute polling (72/day) + 3-hourly forecast (8/day).
    india_energy_atlas_poll_minutes: float = Field(default=20.0, ge=5.0, le=240.0)
    india_energy_atlas_forecast_hours: float = Field(default=3.0, ge=1.0, le=24.0)
    provider_timeout_seconds: float = 30.0  # India Energy Atlas often takes 5–10 s to answer

    # Set automatically by Render (e.g. https://carbon-debt.onrender.com); allowed as a CORS origin.
    render_external_url: str | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        origins = [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]
        if self.render_external_url and self.render_external_url.rstrip("/") not in origins:
            origins.append(self.render_external_url.rstrip("/"))
        return origins

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
