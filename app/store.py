"""In-memory database tables (spec §10): trains, stations, train_routes,
live_train_positions, eta_predictions, actual_movements, operational_events.

Demo config keeps these in RAM; the table layout mirrors the SQLAlchemy models
for the production phase (PostgreSQL), so the swap is mechanical.
"""
from collections import defaultdict, deque


class Store:
    def __init__(self):
        self.live_positions = {}                      # train -> latest live record
        self.position_ring = defaultdict(lambda: deque(maxlen=120))
        self.eta_predictions = defaultdict(list)      # train -> snapshot records
        self.actual_movements = defaultdict(list)     # train -> actual station passes
        self.operational_events = []                  # fired/active events
        self.ingestion_log = deque(maxlen=500)

    def reset_run_data(self):
        self.live_positions.clear()
        self.position_ring.clear()
        self.eta_predictions.clear()
        self.actual_movements.clear()
        self.operational_events.clear()
        self.ingestion_log.clear()

    def record_snapshot(self, train: str, rec: dict, cap: int = 400):
        lst = self.eta_predictions[train]
        lst.append(rec)
        if len(lst) > cap:
            del lst[: len(lst) - cap]

    def mae(self, train: str) -> dict:
        errs = [s["error_min"] for r in self.eta_predictions.get(train, [])
                for s in r["stations"] if s.get("error_min") is not None]
        return {"n": len(errs), "mae_min": round(sum(map(abs, errs)) / len(errs), 1) if errs else None}


STORE = Store()
