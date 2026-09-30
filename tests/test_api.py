"""API integration tests (spec §16). Run: python3 -m pytest tests/ -q"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

from app.config import settings
from app.data import HERO, NETWORK
from app.main import app
from app.sim import SIM

KEY = {"X-API-Key": settings.INGEST_API_KEY}
C = TestClient(app)


def setup_module(_):
    SIM.start(reset=True)  # fresh scripted timeline for every test run


def test_health():
    r = C.get("/api/v1/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_trains_list():
    r = C.get("/api/v1/trains")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == len(NETWORK.trains)
    assert all("train_number" in t for t in body["trains"])


def test_train_detail_and_404():
    assert C.get(f"/api/v1/trains/{HERO}").status_code == 200
    r = C.get("/api/v1/trains/99999")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "TRAIN_NOT_FOUND"


def test_live_shape():
    r = C.get(f"/api/v1/trains/{HERO}/live")
    assert r.status_code == 200
    d = r.json()
    for f in ("train_number", "train_name", "current_position", "current_speed_kmph",
              "current_delay_minutes", "next_station", "status", "last_updated"):
        assert f in d
    assert -90 <= d["current_position"]["latitude"] <= 90
    assert d["last_updated"].endswith("+05:30")


def test_eta_hero_starts_at_demo_arrival():
    """Spec §20: hero train initially predicted at DEMO_ARRIVAL_HHMM (10:30)."""
    SIM.start(reset=True)
    r = C.get(f"/api/v1/trains/{HERO}/eta")
    assert r.status_code == 200
    p = r.json()
    dest = p["predictions"][-1]
    assert dest["scheduled_arrival"] == settings.DEMO_ARRIVAL_HHMM
    assert dest["predicted_arrival"] == settings.DEMO_ARRIVAL_HHMM  # on time, no disruption yet
    assert 0 <= dest["confidence"] <= 1 and dest["uncertainty_minutes"] > 0


def test_disruption_slips_eta_dynamically():
    """Spec §20: introduce disruption -> prediction automatically updates later."""
    SIM.start(reset=True)
    r0 = C.get(f"/api/v1/trains/{HERO}/eta").json()["predictions"][-1]
    assert r0["predicted_arrival"] == settings.DEMO_ARRIVAL_HHMM
    time.sleep(26)                       # CONGESTION (+6) fires at t=20s
    r1 = C.get(f"/api/v1/trains/{HERO}/eta").json()["predictions"][-1]
    assert r1["predicted_delay_minutes"] > 3
    assert r1["predicted_arrival"] > settings.DEMO_ARRIVAL_HHMM
    assert r1["causes"], "cause attribution expected after disruption"
    SIM.start(reset=True)                # leave a clean timeline for later tests


def test_route():
    r = C.get(f"/api/v1/trains/{HERO}/route")
    assert r.status_code == 200
    stops = r.json()["stops"]
    assert len(stops) == NETWORK.trains[HERO].n
    assert stops[0]["seq"] == 0


def test_station_endpoints():
    code = NETWORK.trains[HERO].stops[-1].code
    assert C.get(f"/api/v1/stations/{code}").status_code == 200
    assert C.get(f"/api/v1/stations/{code}/arrivals").status_code == 200
    assert C.get(f"/api/v1/stations/{code}/departures").status_code == 200
    r = C.get("/api/v1/stations/ZZZZ")
    assert r.status_code == 404 and r.json()["error"]["code"] == "STATION_NOT_FOUND"


def test_prediction_store_and_history():
    r = C.post("/api/v1/predictions", json={"train_number": HERO})
    assert r.status_code == 200
    h = C.get(f"/api/v1/predictions/{HERO}/history")
    assert h.status_code == 200
    assert h.json()["snapshots"] >= 1
    assert C.get(f"/api/v1/predictions/{HERO}").status_code == 200


def test_ingestion_requires_api_key():
    r = C.post("/api/v1/data/gps", json={"train_number": HERO, "latitude": 25.0,
                                         "longitude": 89.0, "speed_kmph": 70})
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHORIZED"


def test_ingestion_with_key():
    assert C.post("/api/v1/data/gps", headers=KEY, json={
        "train_number": HERO, "latitude": 25.0, "longitude": 89.0,
        "speed_kmph": 70}).status_code == 200
    assert C.post("/api/v1/data/operations", headers=KEY, json={
        "train_number": HERO, "kind": "CONGESTION", "add_minutes": 3}).status_code == 200
    assert C.post("/api/v1/data/weather", headers=KEY, json={
        "condition": "fog", "visibility_m": 80, "add_minutes": 2}).status_code == 200
    code = NETWORK.trains[HERO].stops[-2].code
    assert C.post("/api/v1/data/actual-arrival", headers=KEY, json={
        "train_number": HERO, "station_code": code,
        "actual_delay_minutes": 4.0}).status_code == 200


def test_validation_error_422():
    r = C.post("/api/v1/data/gps", headers=KEY, json={"train_number": HERO, "latitude": 999})
    assert r.status_code == 422


def test_simulator_controls():
    assert C.post("/api/v1/simulator/stop").json()["status"] == "stopped"
    st = C.get("/api/v1/simulator/status").json()
    assert st["running"] is False
    assert C.post("/api/v1/simulator/start").json()["status"] == "started"
    st = C.get("/api/v1/simulator/status").json()
    assert st["running"] is True and st["hero_train"] == HERO


def test_model_and_metrics():
    assert C.get("/api/v1/model").json()["active_model"] == settings.MODEL_NAME
    assert C.get("/api/v1/metrics").status_code == 200
