"""Shared FastAPI dependencies."""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, Request, status

from ..config import Settings
from ..services.experiments import ExperimentService
from ..services.live import LiveService
from ..services.modes import ModeManager
from ..services.simulation import SimulationService


def modes(request: Request) -> ModeManager:
    return request.app.state.modes


def sim(request: Request) -> SimulationService:
    """The service for the active mode (Simulation or Live); both share one API."""
    return request.app.state.modes.active()


def live(request: Request) -> LiveService:
    return request.app.state.modes.live


def experiments(request: Request) -> ExperimentService:
    return request.app.state.experiments


def settings(request: Request) -> Settings:
    return request.app.state.settings


def require_admin(request: Request, x_admin_token: str | None = Header(default=None)) -> None:
    """Mutating endpoints require X-Admin-Token when ADMIN_TOKEN is configured.

    Local development leaves ADMIN_TOKEN empty; any public deployment must set it.
    """
    token = request.app.state.settings.admin_token
    if token and not hmac.compare_digest((x_admin_token or "").encode(), token.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing or invalid X-Admin-Token")
