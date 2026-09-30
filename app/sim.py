"""Mock railway-data simulator (spec §14, §20).

Stands in for RTIS/NTES live feeds. Deterministic wall-clock driven:
  sim_minutes = SIM_ORIGIN + banked + elapsed_running_seconds * SIM_SPEED

The DEMO STORY (spec §20): hero train starts on time, destination predicted at
DEMO_ARRIVAL_HHMM (10:30). Scripted congestion (~20 s) and a temporary speed
restriction (~45 s) then push the predicted arrival later — demonstrating
dynamic re-prediction on new operational data.
"""
import math
import time
from datetime import date, datetime, timedelta, timezone

from .config import settings
from .data import HERO, NETWORK
from .engine import causes_for, get_model
from .store import STORE

IST = timezone(timedelta(hours=5, minutes=30))
DEMO_H, DEMO_M = map(int, settings.DEMO_ARRIVAL_HHMM.split(":"))
DEMO_ARR_MIN = DEMO_H * 60 + DEMO_M
DAY = date(2026, 9, 30)


def iso(min_abs: float) -> str:
    dt = datetime.combine(DAY, datetime.min.time(), tzinfo=IST) + timedelta(minutes=min_abs % 1440)
    return dt.isoformat(timespec="seconds")


def hhmm(min_abs: float) -> str:
    m = int(round(min_abs)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def phase(no: str) -> float:
    return (sum(map(ord, no)) % 100) / 17.0


class Simulator:
    def __init__(self):
        self.model = get_model()
        self.running = False
        self.run_start = time.time()
        self.banked_s = 0.0
        self._last_bucket = -1
        self._arr_el = None
        self._prev_pos = {}
        self._build()

    # ---------- setup ----------
    def _build(self):
        hero = NETWORK.trains[HERO]
        self.k0 = {}
        self.origin = {}
        hero_k0 = max(2, hero.n - 7)                     # ~6 sections of runway
        sim_origin = (DEMO_ARR_MIN - hero.stops[-1].sched_offset_min
                      + hero.stops[hero_k0].sched_offset_min) % 1440
        for no, rt in NETWORK.trains.items():
            if no == HERO:
                k0 = hero_k0
            else:
                k0 = 2 + (sum(map(ord, no)) % max(1, rt.n - 5))
            self.k0[no] = k0
            self.origin[no] = (sim_origin - rt.stops[k0].sched_offset_min) % 1440
        self.state = {no: {"shock": 0.0, "arrived": False, "arr_min": None,
                           "gps_override": None} for no in NETWORK.trains}
        hk = self.k0[HERO]
        self.events = [
            self._evt(20, "CONGESTION", HERO, hk + 1, hk + 1, 6,
                      "Track congestion ahead of hero train (simulated)"),
            self._evt(45, "TSR", HERO, hk + 3, hk + 4, 5,
                      "Temporary speed restriction 30 km/h (simulated)"),
            self._evt(35, "FOG", NETWORK.order[1], self.k0[NETWORK.order[1]] + 1,
                      self.k0[NETWORK.order[1]] + 2, 7, "Low visibility — dense fog (simulated)"),
            self._evt(75, "FOG", NETWORK.order[2], self.k0[NETWORK.order[2]] + 1,
                      self.k0[NETWORK.order[2]] + 2, 6, "Low visibility — fog bank (simulated)"),
        ]

    def _evt(self, at_s, kind, train, frm, to, add, desc):
        return {"at_s": at_s, "kind": kind, "train": train, "frm": frm, "to": to,
                "add": add, "description": desc, "fired": False, "source": "scripted"}

    # ---------- clock ----------
    def start(self, reset: bool = True):
        if reset:
            self.banked_s = 0.0
            self._arr_el = None
            self._build()
            STORE.reset_run_data()
            self._last_bucket = -1
            self._prev_pos.clear()
        self.run_start = time.time()
        self.running = True

    def stop(self):
        if self.running:
            self.banked_s += time.time() - self.run_start
            self.running = False

    def elapsed(self) -> float:
        """Running real-seconds since (re)start."""
        return self.banked_s + ((time.time() - self.run_start) if self.running else 0.0)

    def sim_now_min(self) -> float:
        hero = NETWORK.trains[HERO]
        hk = self.k0[HERO]
        sim_origin = (DEMO_ARR_MIN - hero.stops[-1].sched_offset_min
                      + hero.stops[hk].sched_offset_min) % 1440
        return sim_origin + self.elapsed() * settings.SIM_SPEED

    # ---------- per-request update ----------
    def tick(self):
        el = self.elapsed()
        # auto-replay: 12 s after the hero train arrives, restart the demo story
        if self.state[HERO]["arrived"] and self.running:
            if self._arr_el is None:
                self._arr_el = el
            elif el - self._arr_el > 12:
                self.start(reset=True)
                el = self.elapsed()
        m = get_model()
        for no, rt in NETWORK.trains.items():
            st = self.state[no]
            if st["arrived"]:
                continue
            pos = min(self.k0[no] + el / settings.SECTION_REAL_S, rt.n - 1)
            for e in self.events:
                if (not e["fired"] and el >= e["at_s"] and e["train"] in (no, "ALL")
                        and int(pos) >= e["frm"]):
                    e["fired"] = True
                    st["shock"] += e["add"]
                    STORE.operational_events.append({
                        "sim_time": iso(self.sim_now_min()), "kind": e["kind"], "train": e["train"],
                        "section": f"{rt.stops[e['frm']].code}–{rt.stops[min(e['to'], rt.n - 1)].code}",
                        "add_minutes": e["add"], "description": e["description"], "source": e["source"]})
            # station passes -> actual movements (spec §3D)
            prev = self._prev_pos.get(no, self.k0[no])
            for j in range(int(prev) + 1, int(pos) + 1):
                if j <= self.k0[no]:
                    continue
                actual_delay = max(0.0, self.delay(no) + math.sin(j * 1.7 + phase(no)) * 0.8)
                sched_arr = self.origin[no] + rt.stops[j].sched_offset_min
                rec = {"station": rt.stops[j].code, "name": rt.stops[j].name,
                       "scheduled_arrival": iso(sched_arr), "actual_arrival": iso(sched_arr + actual_delay),
                       "delay_min": round(actual_delay, 1), "error_min": None}
                # match against most recent prediction snapshot that covered this station
                for snap in reversed(STORE.eta_predictions.get(no, [])):
                    for s in snap["stations"]:
                        if s["station"] == rt.stops[j].code and s.get("error_min") is None:
                            s["error_min"] = round(actual_delay - s["pred_delay"], 1)
                            rec["error_min"] = s["error_min"]
                            break
                    if rec["error_min"] is not None:
                        break
                STORE.actual_movements[no].append(rec)
                if j == rt.n - 1:
                    st["arrived"] = True
                    st["arr_min"] = sched_arr + actual_delay
            self._prev_pos[no] = pos
            # prediction snapshots every SNAPSHOT_REAL_S for historical learning
        bucket = int(el / settings.SNAPSHOT_REAL_S)
        if bucket != self._last_bucket:
            self._last_bucket = bucket
            for no in NETWORK.trains:
                if self.state[no]["arrived"]:
                    continue
                p = self.predict(no)
                STORE.record_snapshot(no, {
                    "generated_at": p["prediction_generated_at"],
                    "model": m.name,
                    "stations": [{"station": x["station_code"], "pred_delay": x["predicted_delay_minutes"],
                                  "pred_arrival": x["predicted_arrival"], "error_min": None}
                                 for x in p["predictions"][:12]]})

    # ---------- core state ----------
    def delay(self, no: str) -> float:
        st = self.state[no]
        wobble = 0.8 * math.sin(self.elapsed() / 9.0 + phase(no))
        return max(0.0, st["shock"] + wobble)

    def pos(self, no: str) -> float:
        rt = NETWORK.trains[no]
        if self.state[no]["arrived"]:
            return float(rt.n - 1)
        return min(self.k0[no] + self.elapsed() / settings.SECTION_REAL_S, rt.n - 1)

    def status(self, no: str) -> str:
        if self.state[no]["arrived"]:
            return "ARRIVED"
        if not self.running:
            return "HELD"
        return "RUNNING"

    def predict(self, no: str) -> dict:
        """ETA for all upcoming stations (spec §5), continuous-update safe."""
        rt = NETWORK.trains[no]
        m = self.model
        k = int(self.pos(no))
        d0 = self.delay(no)
        shock = self.state[no]["shock"]
        active = [e for e in self.events if e["fired"]]
        preds = []
        for j in range(k + 1, rt.n):
            stop = rt.stops[j]
            o = j - k
            pd = max(0.0, m.station_delay(rt, k, j, d0, shock))
            sched_arr = self.origin[no] + stop.sched_offset_min
            preds.append({
                "station_code": stop.code, "station_name": stop.name,
                "scheduled_arrival": hhmm(sched_arr), "scheduled_departure": hhmm(sched_arr + 3),
                "predicted_arrival": hhmm(sched_arr + pd), "predicted_departure": hhmm(sched_arr + pd + 3),
                "predicted_delay_minutes": round(pd, 1),
                "confidence": m.confidence(o), "uncertainty_minutes": m.uncertainty(o),
                "causes": [] if shock <= 0.3 else causes_for(no, k, j, active, stop.hist_delay_min)})
        return {"train_number": no, "prediction_generated_at": iso(self.sim_now_min()),
                "model": m.name, "predictions": preds}

    # ---------- ingestion overrides ----------
    def apply_gps(self, no: str, lat: float, lon: float, speed: float):
        self.state[no]["gps_override"] = {"latitude": lat, "longitude": lon,
                                          "speed_kmph": speed, "at": iso(self.sim_now_min())}
        STORE.ingestion_log.append({"kind": "gps", "train": no})

    def apply_ops_event(self, payload: dict):
        no = payload.get("train_number") or "ALL"
        rt = NETWORK.trains.get(no)
        k = int(self.pos(no)) if rt else 0
        e = {"at_s": -1, "kind": payload.get("kind", "CONGESTION").upper(), "train": no,
             "frm": k + 1, "to": k + int(payload.get("sections_ahead", 2)),
             "add": float(payload.get("add_minutes", 5)),
             "description": payload.get("description", "Ingested operational event"),
             "fired": False, "source": "ingest"}
        e["fired"] = True  # ingested events are already observed reality
        for t in ([no] if no != "ALL" else list(NETWORK.trains)):
            self.state[t]["shock"] += e["add"]
        self.events.append(e)
        STORE.operational_events.append({
            "sim_time": iso(self.sim_now_min()), "kind": e["kind"], "train": no,
            "section": "ahead", "add_minutes": e["add"],
            "description": e["description"], "source": "ingest"})

    def apply_weather(self, payload: dict):
        self.apply_ops_event({"train_number": payload.get("train_number") or "ALL",
                              "kind": payload.get("kind", "WEATHER").upper(),
                              "add_minutes": payload.get("add_minutes", 4),
                              "description": f"Weather: {payload.get('condition', 'adverse')} "
                                             f"(visibility {payload.get('visibility_m', 'n/a')} m)"})

    def apply_actual_arrival(self, no: str, station_code: str, delay_min: float):
        rt = NETWORK.trains[no]
        j = next((s.seq for s in rt.stops if s.code == station_code), None)
        if j is None:
            return None
        sched_arr = self.origin[no] + rt.stops[j].sched_offset_min
        rec = {"station": station_code, "name": rt.stops[j].name,
               "scheduled_arrival": iso(sched_arr),
               "actual_arrival": iso(sched_arr + delay_min),
               "delay_min": round(delay_min, 1), "error_min": None}
        STORE.actual_movements[no].append(rec)
        STORE.ingestion_log.append({"kind": "actual-arrival", "train": no, "station": station_code})
        return rec


SIM = Simulator()
SIM.start(reset=True)
