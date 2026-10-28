"""Live mode: India Energy Atlas client, process monitoring, measured accounting, no fake data."""

import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.ledger import EventType
from app.db import Database
from app.main import create_app
from app.models import GridReadingRow, LedgerRow
from app.services.india_energy_atlas import IndiaEnergyAtlas, ProviderError
from app.services.live import GridFeed, LiveService
from app.services.system_monitor import SystemMonitor, _Window

from .conftest import make_settings


def mock(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------- provider
def test_latest_parses_documented_schema():
    seen = {}

    def handler(request):
        seen["key"] = request.headers.get("X-API-Key")
        seen["path"] = request.url.path
        return httpx.Response(200, json={"as_of": "2026-04-20T14:30:00Z", "scope": "national",
                                         "intensity_gco2_per_kwh": 692, "dominant_fuel": "coal"})

    r = IndiaEnergyAtlas(Settings(india_energy_atlas_api_key="iea_live_test"), mock(handler)).latest()
    assert seen == {"key": "iea_live_test", "path": "/developer/v1/carbon-intensity/latest"}
    assert r.intensity == Decimal("692.00") and r.scope == "national" and r.as_of.tzinfo is not None


def test_latest_parses_live_items_schema():
    # Shape observed from the real API: hourly rows under data.items, newest first.
    items = [{"timestamp": "2026-10-28T03:00:00+00:00", "state": "All India", "carbon_intensity_gco2_kwh": 753.07,
              "fuel_mix_mw": {"coal": 157359.79, "thermal": 139348.12, "solar": 51078.25}},
             {"timestamp": "2026-10-28T02:00:00+00:00", "state": "All India", "carbon_intensity_gco2_kwh": 687.7}]
    client = mock(lambda r: httpx.Response(200, json={"data": {"items": items}}))
    r = IndiaEnergyAtlas(Settings(india_energy_atlas_api_key="k"), client).latest()
    assert r.intensity == Decimal("753.07") and r.as_of.hour == 3 and r.dominant_fuel == "coal"
    assert r.scope == "All India"


def test_forecast_parses_documented_schema():
    items = [{"timestamp": f"2026-04-20T{h:02d}:00:00+05:30", "state": "All India", "state_slug": "all-india",
              "carbon_intensity_gco2_kwh": 600 + h, "is_forecast": True} for h in range(3)]
    client = mock(lambda r: httpx.Response(200, json={"data": {"items": items, "count": 3}, "meta": {}}))
    pts = IndiaEnergyAtlas(Settings(india_energy_atlas_api_key="k"), client).forecast(3)
    assert [float(p.intensity) for p in pts] == [600, 601, 602] and pts[0].timestamp.tzinfo == timezone.utc


def test_missing_key_is_a_clear_error_without_network():
    with pytest.raises(ProviderError, match="INDIA_ENERGY_ATLAS_API_KEY") as e:
        IndiaEnergyAtlas(Settings(india_energy_atlas_api_key=None)).latest()
    assert e.value.code == "missing_api_key"


@pytest.mark.parametrize("status,code", [(401, "invalid_api_key"), (402, "feature_not_in_plan"), (429, "rate_limited")])
def test_provider_errors_keep_code_and_hint(status, code):
    client = mock(lambda r: httpx.Response(status, json={"detail": {"code": code, "message": "nope"}}))
    with pytest.raises(ProviderError) as e:
        IndiaEnergyAtlas(Settings(india_energy_atlas_api_key="k"), client).latest()
    assert e.value.code == code and e.value.status == status


def test_implausible_values_rejected():
    client = mock(lambda r: httpx.Response(200, json={"as_of": "2026-04-20T14:30:00Z", "intensity_gco2_per_kwh": -4}))
    with pytest.raises(ProviderError):
        IndiaEnergyAtlas(Settings(india_energy_atlas_api_key="k"), client).latest()


# ---------------------------------------------------------- process monitor
def test_process_monitor_sees_processes_open_and_close():
    mon = SystemMonitor(1.0)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        time.sleep(0.5)
        mon.sample()
        pids = {p["pid"] for p in mon.snapshot()["processes"]}
        assert child.pid in pids
        row = next(p for p in mon.snapshot()["processes"] if p["pid"] == child.pid)
        assert set(row) >= {"name", "pid", "cpu_percent", "memory_mb", "status", "started_at"}
    finally:
        child.kill()
        child.wait()
    mon.sample()
    assert child.pid not in {p["pid"] for p in mon.snapshot()["processes"]}
    system = mon.snapshot()["system"]
    assert 0 <= system["cpu_percent"] <= 100 and system["memory_total_gb"] > 0


# --------------------------------------------------------- live accounting
class FakeMeter:
    available = True
    source = "test meter"
    message = ""


class FakeMonitor:
    """Stands in for the energy meter so the accounting is deterministic in tests."""

    meter = FakeMeter()
    running = True

    def consume_window(self):
        return _Window(package_j=300.0, busy_cpu_s=2.0, seconds=30.0)

    def snapshot(self):
        return {"energy_meter": {"available": True}, "system": {}, "processes": []}

    def start(self):
        pass

    def stop(self):
        pass


def test_grid_feed_retries_soon_after_timeout_but_not_after_auth_errors(tmp_path):
    settings = make_settings(tmp_path, india_energy_atlas_api_key="k")
    db = Database(settings.live_database_url)
    db.create_all()

    def slow(request):
        raise httpx.ReadTimeout("slow", request=request)

    feed = GridFeed(db, settings, IndiaEnergyAtlas(settings, mock(slow)))
    assert not feed.fetch_latest()
    assert feed.last_error["code"] == "unreachable" and feed.next_interval_s() == 120
    assert feed.status()["state"] == "error"
    feed.provider = IndiaEnergyAtlas(settings, mock(lambda r: httpx.Response(401, json={"detail": {"code": "invalid_api_key"}})))
    assert not feed.fetch_latest()
    assert feed.next_interval_s() == settings.india_energy_atlas_poll_minutes * 60


def live_service(tmp_path, with_reading=True):
    settings = make_settings(tmp_path)
    db = Database(settings.live_database_url)
    db.create_all()
    svc = LiveService(db, settings, FakeMonitor(), GridFeed(db, settings))
    svc.ensure_initialised()
    if with_reading:
        with db.session() as s:
            s.add(GridReadingRow(kind="actual", as_of=datetime.now(timezone.utc) - timedelta(minutes=5),
                                 intensity=Decimal("700"), scope="national", provider="India Energy Atlas"))
    return svc


def test_live_job_measured_energy_and_debt(tmp_path):
    svc = live_service(tmp_path)
    svc.create_job({"name": "Emergency", "workload": "triage-ai", "job_class": "emergency", "priority": 1,
                    "runtime_min": 1, "deadline_offset_min": 2, "arrival_offset_min": 0})
    with svc.db.session() as s:  # open the first slot
        clock = svc.clock(s)
        clock.epoch = datetime.now(timezone.utc) - timedelta(seconds=5)
    assert svc.live_tick(force=True)["advanced"]
    try:
        for _ in range(2):  # a 1-minute job = two 30-second slots
            time.sleep(0.6)  # let the bounded worker burn some real CPU
            assert svc.live_tick(force=True)["advanced"]
        job = svc.job_detail("J-0001")
        assert job["job"]["state"] == "completed"
        execs = job["executions"]
        assert execs and all(e["energy_source"] == "MEASURED_RAPL_ATTRIBUTED" for e in execs)
        assert all(e["kernel_cpu_ms"] > 0 for e in execs)  # real CPU time was recorded
        assert job["job"]["debt_g"] > 0  # 700 > 350 gCO2e/kWh threshold
        with svc.db.session() as s:
            types = [r.event_type for r in s.query(LedgerRow).order_by(LedgerRow.seq)]
        assert EventType.DEBT_INCURRED in types
        assert svc.verify_ledger()["status"] == "VERIFIED"
    finally:
        svc.workers.stop_all()


def test_no_grid_reading_means_no_scheduling_and_no_fake_value(tmp_path):
    svc = live_service(tmp_path, with_reading=False)
    svc.create_job({"name": "Batch", "workload": "w", "job_class": "normal", "priority": 3,
                    "runtime_min": 2, "deadline_offset_min": 10, "arrival_offset_min": 0})
    assert svc.live_tick(force=True)["advanced"] is False
    state = svc.state()
    assert state["carbon"]["intensity"] is None and state["carbon"]["source"] == "UNAVAILABLE"
    assert state["live"]["grid"]["state"] == "not_configured"
    assert svc.carbon_curve()["points"] == []


def test_job_created_while_idle_arrives_now(tmp_path):
    svc = live_service(tmp_path)
    with svc.db.session() as s:
        svc.clock(s).epoch = datetime.now(timezone.utc) - timedelta(minutes=30)  # idle for 30 minutes
    job = svc.create_job({"name": "Batch", "workload": "w", "job_class": "normal", "priority": 3,
                          "runtime_min": 2, "deadline_offset_min": 10, "arrival_offset_min": 0})["job"]
    assert job["arrival_slot"] == 60  # 30 min of 30-second slots, not slot 0
    assert job["deadline_slot"] == 80


def test_live_job_limits(tmp_path):
    svc = live_service(tmp_path)
    from app.services.simulation import InvalidInput
    with pytest.raises(InvalidInput):
        svc.create_job({"name": "Huge", "workload": "w", "job_class": "normal", "priority": 3,
                        "runtime_min": 60, "deadline_offset_min": 90, "arrival_offset_min": 0})


def test_missing_key_feed_status(tmp_path):
    svc = live_service(tmp_path, with_reading=False)
    assert svc.feed.fetch_latest() is False
    status = svc.feed.status()
    assert status["state"] == "not_configured" and "INDIA_ENERGY_ATLAS_API_KEY" in status["error"]["message"]


# ---------------------------------------------------------------- modes API
def test_mode_switch_api(tmp_path):
    with TestClient(create_app(make_settings(tmp_path), start_background=False)) as c:
        assert c.get("/api/mode").json()["mode"] == "simulation"
        assert c.get("/api/state").json()["carbon"]["mode"] == "SIMULATED"
        assert c.post("/api/live/monitoring", json={"enabled": True}).status_code == 409  # not in Live mode yet
        assert c.put("/api/mode", json={"mode": "live"}).json()["mode"] == "live"
        state = c.get("/api/state").json()
        assert state["carbon"]["mode"] == "LIVE" and state["carbon"]["intensity"] is None  # no key → no value
        assert c.post("/api/scenario/run", json={"mode": "instant"}).status_code == 422
        assert c.post("/api/sim/advance", json={"slots": 1}).status_code == 422
        assert c.get("/api/live/status").json()["grid"]["state"] == "not_configured"
        assert c.put("/api/mode", json={"mode": "simulation"}).json()["mode"] == "simulation"
        assert c.get("/api/jobs").json() == []  # live jobs never appear in simulation


def test_begin_finish_equals_step(demo_engine):
    a, b = demo_engine(), demo_engine()
    for _ in range(40):
        a.step()
        b.begin_slot()
        b.finish_slot()
    assert [r.hash for r in a.ledger.new_records] == [r.hash for r in b.ledger.new_records]
