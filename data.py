"""Load the self-contained sample network snapshot (sample_data/network.json)."""
import json
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Stop:
    seq: int
    code: str
    name: str
    sched_offset_min: int
    distance_km: float
    hist_delay_min: float


@dataclass
class TrainRoute:
    number: str
    name: str
    type: str
    stops: list = field(default_factory=list)

    @property
    def n(self):
        return len(self.stops)


class Network:
    def __init__(self):
        doc = json.load(open(ROOT / "sample_data" / "network.json"))
        self.source = doc["source"]
        self.stations = doc["stations"]
        self.sec = doc["sec"]
        self.off = {int(k): v for k, v in doc["off"].items()}
        self.trains = {}
        for t in doc["trains"]:
            stops = [Stop(**s) for s in t["route"]]
            self.trains[t["number"]] = TrainRoute(t["number"], t["name"], t["type"], stops)
        self.order = list(self.trains)

    def off_med(self, o: int) -> float:
        return self.off.get(min(o, 17), self.off.get(17, 0.0))


NETWORK = Network()
HERO = NETWORK.order[0]  # demo train for the 10:30 dynamic-ETA story (spec §20)
