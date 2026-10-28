"""The simplified demonstration flow: sample processes, one-click grid levels, plain-English reasons."""

from __future__ import annotations


def jobs_by_name(client) -> dict[str, dict]:
    return {j["name"]: j for j in client.get("/api/jobs").json()}


def step(client, n: int = 1) -> None:
    assert client.post("/api/sim/advance", json={"slots": n}).status_code == 200


def test_coal_then_green_demo_flow(client):
    assert client.post("/api/demo/samples").json()["loaded"] == ["J-0001", "J-0002", "J-0003", "J-0004"]
    assert {j["status_label"] for j in jobs_by_name(client).values()} == {"Waiting"}
    r = client.post("/api/sim/grid", json={"preset": "coal"})
    assert r.status_code == 200 and r.json()["intensity"] == 650
    state = client.get("/api/state").json()
    assert state["carbon"]["intensity"] == 650 and state["carbon"]["manual"]["preset"] == "coal"

    step(client)  # 06:00 at 650 gCO2e/kWh
    jobs = jobs_by_name(client)
    emergency = jobs["Hospital alert system"]
    assert emergency["status_label"] == "Running"
    assert emergency["plain_reason"] == "Running now because this is an emergency."
    backup = jobs["Nightly data backup"]
    assert backup["state"] == "deferred" and backup["status_label"] == "Scheduled for later"
    assert backup["plain_reason"].startswith("Scheduled for ") and "cleaner electricity is expected" in backup["plain_reason"]
    assert jobs["Payroll report"]["state"] == "running"  # short deadline: cannot wait

    client.post("/api/sim/grid", json={"preset": "green"})
    step(client)  # 06:15 green
    jobs = jobs_by_name(client)
    assert jobs["Nightly data backup"]["state"] == "running"
    assert "electricity is clean" in jobs["Nightly data backup"]["plain_reason"]

    step(client, 6)
    ledger = client.get("/api/state").json()["ledger"]
    assert ledger["total_debt_g"] > 0
    assert ledger["credits_applied_g"] > 0
    assert ledger["effective_g"] == round(ledger["total_debt_g"] - ledger["credits_applied_g"], 6)
    assert client.get("/api/ledger/verify").json()["ok"]


def test_threshold_policy_waits_instead_of_booking_a_time(client):
    client.put("/api/controller/settings", json={"policy": "threshold"})
    client.post("/api/demo/samples")
    client.post("/api/sim/grid", json={"preset": "coal"})
    step(client)
    backup = jobs_by_name(client)["Nightly data backup"]
    assert backup["status_label"] == "Waiting"
    assert backup["plain_reason"] == "Waiting because electricity is carbon-intensive and this process can wait."


def test_grid_history_is_kept_and_reset_restores_normal_pattern(client):
    client.post("/api/demo/samples")
    client.post("/api/sim/grid", json={"preset": "coal"})
    step(client)
    client.post("/api/sim/grid", json={"preset": "custom", "intensity": 300, "hours": 1})
    curve = {p["slot"]: p for p in client.get("/api/carbon/curve").json()["points"]}
    assert curve[24]["intensity"] == 650 and curve[25]["intensity"] == 300  # the played slot keeps its value
    assert curve[29]["source"] == "SIMULATED"  # after 1 hour the normal pattern resumes
    client.post("/api/sim/grid", json={"preset": "normal"})
    assert client.get("/api/state").json()["carbon"]["manual"] is None
    client.post("/api/demo/reset", json={"confirm": "RESET"})
    assert client.get("/api/controller").json()["settings"]["grid_events"] == []


def test_grid_validation(client):
    assert client.post("/api/sim/grid", json={"preset": "custom"}).status_code == 422
    assert client.post("/api/sim/grid", json={"preset": "custom", "intensity": 5000}).status_code == 422
    client.put("/api/mode", json={"mode": "live"})
    assert client.post("/api/sim/grid", json={"preset": "green"}).status_code == 422


def test_experiment_reports_clean_energy_share():
    from app.core.experiment import ExperimentRequest, run_experiment

    res = run_experiment(ExperimentRequest(seeds=[1], policies=["fifo", "debt_predictive"]))
    agg = res["aggregates"]
    assert 0 <= agg["fifo"]["clean_energy_pct"]["mean"] <= 100
    assert agg["debt_predictive"]["clean_energy_pct"]["mean"] > agg["fifo"]["clean_energy_pct"]["mean"]
