"""SARTHI-ETA API v1 — FastAPI application (spec §3, §8, §12, §13, §15)."""
import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import FastAPI, Header, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel, Field

from . import __version__
from .config import settings
from .data import HERO, NETWORK
from .engine import model_info
from .errors import (STATION_NOT_FOUND, TRAIN_NOT_FOUND, UNAUTHORIZED, ApiError,
                     body, register)
from .sim import SIM, hhmm, iso
from .store import STORE

app = FastAPI(
    title="SARTHI-ETA — Real-Time Dynamic Train ETA API",
    description="Dynamic ETA prediction combining real-time running data, historical "
                "patterns, network conditions and contextual factors (SIH26028, team TURTLEs). "
                "Demo configuration: simulated live feeds over real historical sectional "
                "profiles from the DA323 public dataset. Live RTIS/NTES feeds plug in "
                "behind the same /api/v1 contract.",
    version=__version__)
register(app)

# ---------- rate limiting (spec §13: 429) ----------
_hits = defaultdict(lambda: deque())


@app.middleware("http")
async def _rate_limit(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        ip = request.client.host if request.client else "?"
        now = time.time()
        q = _hits[ip]
        while q and q[0] < now - 60:
            q.popleft()
        if len(q) >= settings.RATE_LIMIT_PER_MIN:
            return JSONResponse(status_code=429, content=body(
                "RATE_LIMIT_EXCEEDED", "Too many requests. Please retry later."))
        q.append(now)
    return await call_next(request)


# ---------- schemas (spec §4, §5) ----------
class LiveResponse(BaseModel):
    train_number: str
    train_name: str
    current_position: dict
    current_speed_kmph: int
    current_delay_minutes: float
    next_station: str
    status: str
    last_updated: str


class PredictionItem(BaseModel):
    station_code: str
    station_name: str
    scheduled_arrival: str
    scheduled_departure: str
    predicted_arrival: str
    predicted_departure: str
    predicted_delay_minutes: float
    confidence: float
    uncertainty_minutes: float
    causes: list


class EtaResponse(BaseModel):
    train_number: str
    prediction_generated_at: str
    model: str
    predictions: list[PredictionItem]


class GpsIn(BaseModel):
    train_number: str
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    speed_kmph: float = Field(..., ge=0, le=250)
    timestamp: Optional[str] = None


class OpsIn(BaseModel):
    train_number: Optional[str] = None
    kind: str = "CONGESTION"
    add_minutes: float = Field(5, ge=0, le=240)
    sections_ahead: int = Field(2, ge=1, le=10)
    description: Optional[str] = None


class WeatherIn(BaseModel):
    train_number: Optional[str] = None
    condition: str = "fog"
    visibility_m: Optional[int] = None
    add_minutes: float = Field(4, ge=0, le=240)


class ActualArrivalIn(BaseModel):
    train_number: str
    station_code: str
    actual_delay_minutes: float = Field(..., ge=-120, le=600)


# ---------- helpers ----------
def _train(no: str):
    if no not in NETWORK.trains:
        raise TRAIN_NOT_FOUND(no)
    return NETWORK.trains[no]


def _station(code: str):
    code = code.upper()
    if code not in NETWORK.stations:
        raise STATION_NOT_FOUND(code)
    return NETWORK.stations[code]


def _live_payload(no: str) -> dict:
    rt = _train(no)
    SIM.tick()
    pos = SIM.pos(no)
    k = int(pos)
    frac = pos - k
    a = NETWORK.stations[rt.stops[k].code]
    b = NETWORK.stations[rt.stops[min(k + 1, rt.n - 1)].code]
    lat = round(a["latitude"] + (b["latitude"] - a["latitude"]) * frac, 4)
    lon = round(a["longitude"] + (b["longitude"] - a["longitude"]) * frac, 4)
    speed = 0 if SIM.state[no]["arrived"] else (10 if frac < 0.06 else
            int(52 + (sum(map(ord, no)) % 15) + 4 * (0.5 + 0.5 * (SIM.elapsed() % 7) / 7)))
    rec = {"train_number": no, "train_name": rt.name,
           "current_position": {"latitude": lat, "longitude": lon},
           "current_speed_kmph": speed,
           "current_delay_minutes": round(SIM.delay(no), 1),
           "next_station": rt.stops[k + 1].code if k + 1 < rt.n else rt.stops[-1].code,
           "status": SIM.status(no),
           "last_updated": iso(SIM.sim_now_min())}
    STORE.live_positions[no] = rec
    STORE.position_ring[no].append(rec)
    return rec


def _require_key(x_api_key: Optional[str]):
    if x_api_key != settings.INGEST_API_KEY:
        raise UNAUTHORIZED


# ---------- Train APIs (spec §8) ----------
@app.get("/api/v1/trains", tags=["trains"])
def list_trains():
    SIM.tick()
    out = []
    for no in NETWORK.order:
        rt = NETWORK.trains[no]
        k = int(SIM.pos(no))
        out.append({"train_number": no, "train_name": rt.name, "type": rt.type,
                    "current_station": rt.stops[k].code,
                    "current_delay_minutes": round(SIM.delay(no), 1),
                    "status": SIM.status(no)})
    return {"count": len(out), "sim_time": iso(SIM.sim_now_min()), "trains": out}


@app.get("/api/v1/trains/{train_number}", tags=["trains"])
def get_train(train_number: str):
    rt = _train(train_number)
    return {"train_number": rt.number, "train_name": rt.name, "type": rt.type,
            "origin": rt.stops[0].code, "destination": rt.stops[-1].code,
            "stops": rt.n, "distance_km": rt.stops[-1].distance_km}


@app.get("/api/v1/trains/{train_number}/live", tags=["trains"], response_model=LiveResponse)
def live(train_number: str):
    return _live_payload(train_number)


@app.get("/api/v1/trains/{train_number}/eta", tags=["trains"], response_model=EtaResponse)
def eta(train_number: str):
    _train(train_number)
    SIM.tick()
    return SIM.predict(train_number)


@app.get("/api/v1/trains/{train_number}/route", tags=["trains"])
def route(train_number: str):
    rt = _train(train_number)
    org = SIM.origin[train_number]
    return {"train_number": rt.number, "train_name": rt.name,
            "stops": [{"seq": s.seq, "station_code": s.code, "station_name": s.name,
                       "scheduled_arrival": hhmm(org + s.sched_offset_min),
                       "distance_km": s.distance_km,
                       "hist_delay_min": s.hist_delay_min} for s in rt.stops]}


# ---------- Station APIs ----------
def _station_board(code: str, horizon_min: float = 360):
    st = _station(code)
    SIM.tick()
    now = SIM.sim_now_min()
    rows = []
    for no in NETWORK.order:
        rt = NETWORK.trains[no]
        hits = [s for s in rt.stops if s.code == code]
        if not hits:
            continue
        s = hits[0]
        p = SIM.predict(no)
        m = next((x for x in p["predictions"] if x["station_code"] == code), None)
        sched = SIM.origin[no] + s.sched_offset_min
        if m:
            pred_delay, conf = m["predicted_delay_minutes"], m["confidence"]
            status = "DUE"
        elif SIM.state[no]["arrived"] or SIM.pos(no) > s.seq:
            act = next((a for a in reversed(STORE.actual_movements[no]) if a["station"] == code), None)
            pred_delay, conf = (act["delay_min"], None) if act else (0.0, None)
            status = "PASSED"
        else:
            pred_delay, conf = 0.0, None
            status = "AT STN"
        arr = sched + (pred_delay if status != "PASSED" else pred_delay)
        if not (now - 30 <= arr <= now + horizon_min) and status != "PASSED":
            continue
        rows.append({"train_number": no, "train_name": rt.name, "status": status,
                     "scheduled_arrival": iso(sched), "predicted_arrival": iso(arr),
                     "predicted_delay_minutes": round(pred_delay, 1),
                     "confidence": conf,
                     "predicted_departure": iso(arr + 3)})
    rows.sort(key=lambda r: r["predicted_arrival"])
    return st, rows


@app.get("/api/v1/stations/{station_code}", tags=["stations"])
def station(station_code: str):
    st, rows = _station_board(station_code)
    return {"station": st, "next_movements": rows[:8]}


@app.get("/api/v1/stations/{station_code}/arrivals", tags=["stations"])
def arrivals(station_code: str):
    _, rows = _station_board(station_code)
    return {"station_code": station_code.upper(), "arrivals": rows}


@app.get("/api/v1/stations/{station_code}/departures", tags=["stations"])
def departures(station_code: str):
    _, rows = _station_board(station_code)
    for r in rows:
        r["scheduled_departure"] = r.pop("scheduled_arrival")
        r["predicted_departure_iso"] = r.pop("predicted_arrival")
    return {"station_code": station_code.upper(), "departures": rows}


# ---------- Prediction APIs (spec §3D: store + evaluate) ----------
class PredictionRequest(BaseModel):
    train_number: str
    note: Optional[str] = None


@app.post("/api/v1/predictions", tags=["predictions"])
def create_prediction(req: PredictionRequest):
    _train(req.train_number)
    SIM.tick()
    p = SIM.predict(req.train_number)
    STORE.record_snapshot(req.train_number, {
        "generated_at": p["prediction_generated_at"], "model": p["model"], "on_demand": True,
        "stations": [{"station": x["station_code"], "pred_delay": x["predicted_delay_minutes"],
                      "pred_arrival": x["predicted_arrival"], "error_min": None}
                     for x in p["predictions"][:12]]})
    return p


@app.get("/api/v1/predictions/{train_number}", tags=["predictions"])
def current_prediction(train_number: str):
    _train(train_number)
    SIM.tick()
    return SIM.predict(train_number)


@app.get("/api/v1/predictions/{train_number}/history", tags=["predictions"])
def prediction_history(train_number: str):
    _train(train_number)
    SIM.tick()
    snaps = STORE.eta_predictions.get(train_number, [])
    return {"train_number": train_number,
            "snapshots": len(snaps),
            "evaluation": STORE.mae(train_number),
            "actual_movements": STORE.actual_movements.get(train_number, []),
            "history": list(reversed(snaps[-20:]))}


# ---------- Data ingestion (spec §8, §12: API-key protected) ----------
@app.post("/api/v1/data/gps", tags=["ingestion"])
def ingest_gps(body_in: GpsIn, x_api_key: Optional[str] = Header(None)):
    _require_key(x_api_key)
    _train(body_in.train_number)
    SIM.tick()
    SIM.apply_gps(body_in.train_number, body_in.latitude, body_in.longitude, body_in.speed_kmph)
    return {"status": "accepted", "train_number": body_in.train_number}


@app.post("/api/v1/data/operations", tags=["ingestion"])
def ingest_ops(body_in: OpsIn, x_api_key: Optional[str] = Header(None)):
    _require_key(x_api_key)
    if body_in.train_number:
        _train(body_in.train_number)
    SIM.tick()
    SIM.apply_ops_event(body_in.model_dump())
    return {"status": "accepted", "event": body_in.kind}


@app.post("/api/v1/data/weather", tags=["ingestion"])
def ingest_weather(body_in: WeatherIn, x_api_key: Optional[str] = Header(None)):
    _require_key(x_api_key)
    if body_in.train_number:
        _train(body_in.train_number)
    SIM.tick()
    SIM.apply_weather(body_in.model_dump())
    return {"status": "accepted", "condition": body_in.condition}


@app.post("/api/v1/data/actual-arrival", tags=["ingestion"])
def ingest_actual(body_in: ActualArrivalIn, x_api_key: Optional[str] = Header(None)):
    _require_key(x_api_key)
    _train(body_in.train_number)
    SIM.tick()
    rec = SIM.apply_actual_arrival(body_in.train_number, body_in.station_code.upper(),
                                   body_in.actual_delay_minutes)
    if rec is None:
        raise STATION_NOT_FOUND(body_in.station_code)
    return {"status": "accepted", "record": rec}


# ---------- Simulator control (spec §14) ----------
@app.post("/api/v1/simulator/start", tags=["simulator"])
def sim_start(reset: bool = True):
    SIM.start(reset=reset)
    return {"status": "started", "reset": reset, "sim_time": iso(SIM.sim_now_min())}


@app.post("/api/v1/simulator/stop", tags=["simulator"])
def sim_stop():
    SIM.stop()
    return {"status": "stopped", "sim_time": iso(SIM.sim_now_min())}


@app.get("/api/v1/simulator/status", tags=["simulator"])
def sim_status():
    SIM.tick()
    hero_p = SIM.predict(HERO)
    dest = hero_p["predictions"][-1] if hero_p["predictions"] else None
    return {"running": SIM.running, "sim_time": iso(SIM.sim_now_min()),
            "sim_clock": hhmm(SIM.sim_now_min()),
            "elapsed_running_seconds": round(SIM.elapsed(), 1),
            "speed": f"{settings.SIM_SPEED} sim-min/sec",
            "hero_train": HERO,
            "hero_demo": {"destination": dest["station_name"] if dest else None,
                          "scheduled_arrival": dest["scheduled_arrival"] if dest else None,
                          "predicted_arrival": dest["predicted_arrival"] if dest else None,
                          "predicted_delay_minutes": dest["predicted_delay_minutes"] if dest else None},
            "events_fired": [e for e in STORE.operational_events],
            "events_pending": [{"at_s": e["at_s"], "kind": e["kind"], "train": e["train"],
                                "add_minutes": e["add"]}
                               for e in SIM.events if not e["fired"] and e["source"] == "scripted"]}


# ---------- Model, health, metrics (spec §11, §15) ----------
@app.get("/api/v1/model", tags=["system"])
def model():
    return model_info()


@app.get("/api/v1/health", tags=["system"])
def health():
    return {"status": "ok", "version": __version__,
            "mode": "demo (simulated feeds over real historical sectional profiles)",
            "model": SIM.model.name, "sim_running": SIM.running,
            "sim_time": iso(SIM.sim_now_min())}


@app.get("/api/v1/metrics", tags=["system"])
def metrics():
    return {"trains_tracked": len(NETWORK.trains),
            "prediction_snapshots": sum(len(v) for v in STORE.eta_predictions.values()),
            "actual_movements_recorded": sum(len(v) for v in STORE.actual_movements.values()),
            "operational_events_fired": len(STORE.operational_events),
            "ingestion_messages": len(STORE.ingestion_log),
            "mae_by_train": {no: STORE.mae(no) for no in NETWORK.order}}


# ---------- demo dashboard (spec §15) ----------
@app.get("/", include_in_schema=False)
def demo_page():
    return FileResponse(Path(__file__).parent.parent / "static" / "demo.html")


app.mount("/static", StaticFiles(directory=Path(__file__).parent.parent / "static"), name="static")
