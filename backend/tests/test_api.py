import time

from fastapi.testclient import TestClient

from app.main import create_app

from .conftest import make_settings

JOB = {"name": "Nightly ETL", "workload": "data-platform", "job_class": "normal", "priority": 3,
       "power_w": 800, "runtime_min": 60, "deadline_offset_min": 480}


def test_health_and_state(client):
    assert client.get("/api/health").json()["status"] == "ok"
    state = client.get("/api/state").json()
    assert state["carbon"]["mode"] == "SIMULATED" and state["ledger"]["balance_g"] == 0


def test_scenario_end_to_end(client):
    res = client.post("/api/scenario/run", json={"mode": "instant"}).json()
    assert res["complete"], res["steps"]
    state = client.get("/api/state").json()
    assert state["ledger"]["total_debt_g"] > 0 and state["ledger"]["credits_applied_g"] > 0
    assert state["ledger"]["balance_g"] == 0
    assert client.get("/api/ledger/verify").json()["status"] == "VERIFIED"
    tamper = client.post("/api/ledger/tamper-demo", json={"field": "amount_g"}).json()
    assert tamper["tampered_copy"]["status"] == "TAMPERED" and tamper["database_modified"] is False
    assert client.get("/api/ledger/verify").json()["status"] == "VERIFIED"  # real ledger untouched
    receipt = client.get("/api/jobs/J-0004/receipt").json()
    assert float(receipt["carbon"]["credit_earned_g"]) > 0 and receipt["deadline"]["met"]
    assert len(client.get("/api/timeline").json()["points"]) == 40
    stats = client.get("/api/stats/workloads").json()
    assert any(s["workload"] == "triage-ai" and s["debt_g"] > 0 for s in stats)


def test_job_validation(client):
    bad = dict(JOB, runtime_min=50)
    assert client.post("/api/jobs", json=bad).status_code == 422
    infeasible = dict(JOB, deadline_offset_min=30)
    assert client.post("/api/jobs", json=infeasible).status_code == 422
    assert client.post("/api/jobs", json=dict(JOB, job_class="urgent")).status_code == 422
    assert client.post("/api/jobs", json=dict(JOB, power_w=-5)).status_code == 422


def test_duplicate_request_is_idempotent(client):
    body = dict(JOB, idempotency_key="req-123")
    first = client.post("/api/jobs", json=body)
    second = client.post("/api/jobs", json=body)
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["job"]["id"] == second.json()["job"]["id"]
    assert len(client.get("/api/jobs").json()) == 1


def test_job_actions_and_invalid_transition(client):
    job_id = client.post("/api/jobs", json=JOB).json()["job"]["id"]
    client.post("/api/sim/advance", json={"slots": 1})
    assert client.post(f"/api/jobs/{job_id}/actions", json={"action": "cancel"}).status_code == 200
    resp = client.post(f"/api/jobs/{job_id}/actions", json={"action": "run"})
    assert resp.status_code == 409
    assert client.get("/api/jobs/J-9999").status_code == 404


def test_settings_change_alters_decisions(client):
    client.post("/api/demo/load")
    # With a very high debt threshold and FIFO, flexible jobs run immediately; with the controller they are deferred.
    client.put("/api/controller/settings", json={"policy": "fifo"})
    client.post("/api/sim/advance", json={"slots": 8})
    fifo_etl = client.get("/api/jobs/J-0004").json()["job"]
    client.post("/api/demo/load")
    client.put("/api/controller/settings", json={"policy": "debt_predictive"})
    client.post("/api/sim/advance", json={"slots": 8})
    ctl_etl = client.get("/api/jobs/J-0004").json()["job"]
    assert fifo_etl["state"] in ("running", "completed") and ctl_etl["state"] == "deferred"
    assert client.put("/api/controller/settings", json={"green_threshold": 900}).status_code == 422
    assert client.put("/api/controller/settings", json={"unknown": 1}).status_code == 422


def test_reset_requires_confirmation(client):
    assert client.post("/api/demo/reset", json={}).status_code == 422
    assert client.post("/api/demo/reset", json={"confirm": "RESET"}).status_code == 200


def test_persistence_across_restart(tmp_path):
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings, start_background=False)) as c:
        c.post("/api/scenario/run", json={"mode": "instant"})
        head = c.get("/api/ledger/verify").json()["head_hash"]
    with TestClient(create_app(settings, start_background=False)) as c:
        verify = c.get("/api/ledger/verify", params={"expected_head": head}).json()
        assert verify["status"] == "VERIFIED" and verify["checked"] > 5
        assert c.get("/api/state").json()["clock"]["slot"] == 64


def test_admin_token_enforced(tmp_path):
    settings = make_settings(tmp_path, admin_token="s3cret")
    with TestClient(create_app(settings, start_background=False)) as c:
        assert c.post("/api/sim/advance", json={"slots": 1}).status_code == 401
        ok = c.post("/api/sim/advance", json={"slots": 1}, headers={"X-Admin-Token": "s3cret"})
        assert ok.status_code == 200
        assert c.get("/api/state").status_code == 200  # reads stay public


def test_simulation_rejects_unaligned_times(client):
    resp = client.post("/api/jobs", json=dict(JOB, runtime_min=20))
    assert resp.status_code == 422 and "multiple of 15" in resp.json()["detail"]


def test_experiment_api(client):
    body = {"name": "tiny", "seeds": [1], "emergency": 1, "normal": 3, "background": 2}
    exp = client.post("/api/experiments", json=body).json()
    for _ in range(100):
        cur = client.get(f"/api/experiments/{exp['id']}").json()
        if cur["status"] in ("completed", "failed"):
            break
        time.sleep(0.1)
    assert cur["status"] == "completed", cur.get("error")
    assert "debt_predictive" in cur["results"]["aggregates"]
    csv = client.get(f"/api/experiments/{exp['id']}/export.csv")
    assert csv.status_code == 200 and "policy" in csv.text.splitlines()[0]
    assert client.get(f"/api/experiments/{exp['id']}/report.json").json()["data_label"].startswith("SIMULATED")
