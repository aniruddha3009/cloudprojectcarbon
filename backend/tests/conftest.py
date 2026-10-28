from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.core.carbon_curve import simulated_curve  # noqa: E402
from app.core.config_model import ControllerConfig  # noqa: E402
from app.core.engine import Engine  # noqa: E402
from app.core.policies import make_policy  # noqa: E402
from app.core.workloads import SCENARIO_START_SLOT, demo_sim_jobs  # noqa: E402
from app.main import create_app  # noqa: E402


def make_settings(tmp_path: Path, **overrides) -> Settings:
    data = {"database_url": f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
            "live_database_url": f"sqlite:///{(tmp_path / 'live.db').as_posix()}",
            "india_energy_atlas_api_key": None,  # never let a real key from .env reach the tests
            "kernel_ms": 0, "log_level": "WARNING"}
    data.update(overrides)
    return Settings(**data)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def client(settings: Settings):
    app = create_app(settings, start_background=False)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def demo_engine():
    def _make(policy: str = "debt_predictive", **cfg_overrides) -> Engine:
        cfg = ControllerConfig(policy=policy, **cfg_overrides)
        curve = simulated_curve(cfg.profile, cfg.seed, cfg.noise_pct)
        return Engine(cfg, curve, demo_sim_jobs(), make_policy(policy), now=SCENARIO_START_SLOT)
    return _make
