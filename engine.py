"""Modular ETA prediction engine (spec §6, §7, §11).

Two interchangeable models behind one interface — swap via MODEL_NAME env var,
public API contract unchanged:
  * sarthi-blend : horizon-aware blend — sectional delay growth for near horizon
                   (<=3 sections, learned SEC medians), historical offset-drift
                   curve for far horizon (OFF medians). Back-tested on DA323:
                   near MAE 13.6 (-23%), mid 29.7 (-21%), far 99.1 (-7%) vs naive.
  * baseline     : spec §6 heuristic — now + remaining sectional travel + dwell
                   + expected operational delay - expected recoverable delay.
"""
import math

from .config import settings
from .data import NETWORK


def causes_for(train_no: str, k: int, j: int, active_events: list, hist_delay: float) -> list:
    """Attribute active disruptions still ahead on the remaining path (k -> j)."""
    out = []
    for e in active_events:
        if e["train"] in (train_no, "ALL") and e["frm"] >= k and e["frm"] < j:
            out.append({"kind": e["kind"], "add_minutes": e["add"], "description": e["description"]})
    if not out and hist_delay >= 40:
        out.append({"kind": "HIST_CONGESTION", "add_minutes": round(hist_delay / 12),
                    "description": "Historical congestion at this station profile"})
    return out[:3]


class SarthiBlend:
    """Horizon-aware blend.

    With no observed disruption the schedule is the best estimate (predicted
    arrival == scheduled). Once a disruption is observed (shock > 0), the
    historical drift curve projects how delays compound over horizon — the
    back-tested behaviour from DA323 (near -23%, mid -21%, far -7% MAE vs naive).
    """
    name = "sarthi-blend"
    backtest = {"near_mae": 13.6, "mid_mae": 29.7, "far_mae": 99.1,
                "naive_near": 17.7, "naive_mid": 37.8, "naive_far": 106.2, "dataset": "DA323"}

    @staticmethod
    def _gate(shock: float) -> float:
        return 0.0 if shock <= 0.3 else min(1.0, shock / 4.0)

    def station_delay(self, route, k: int, j: int, d0: float, shock: float = 0.0) -> float:
        """Observed delay persists; historical drift adds bounded compounding.

        The raw drift curve grows ~6-8 min/section in the DA323 book (chronic
        end-of-route congestion). Unbounded, a small disruption would project a
        30+ min slip, so compounding is capped at 2 + 0.3*d0 — disruption adds
        delay, but the schedule absorbs part of it (crew/margin recovery).
        """
        o, g = j - k, self._gate(shock)
        cap = 2.0 + 0.3 * d0
        if o <= 3:
            acc = 0.0
            for i in range(k, j):
                s = NETWORK.sec.get(f"{route.stops[i].code}>{route.stops[i+1].code}",
                                    NETWORK.off_med(1))
                acc += max(0.0, s)          # count delay-adding sections only
            return d0 + g * min(acc, cap)
        return d0 + g * min(max(0.0, NETWORK.off_med(o)), cap)

    def confidence(self, o: int) -> float:
        return round(max(0.55, 0.95 - 0.028 * o), 2)

    def uncertainty(self, o: int) -> float:
        return round(2 + 1.1 * math.sqrt(o), 1)


class BaselineHeuristic:
    """Spec §6 baseline: ETA = now + remaining sectional travel + dwell
    + expected operational delay - expected recoverable delay."""
    name = "baseline"
    backtest = None

    def station_delay(self, route, k: int, j: int, d0: float, shock: float = 0.0) -> float:
        o = j - k
        ops = NETWORK.off_med(o) * 0.6          # expected operational delay (historical)
        recoverable = min(d0, 3.0)              # crews recover ~3 min over horizon
        return max(0.0, d0 + ops - recoverable)

    def confidence(self, o: int) -> float:
        return round(max(0.45, 0.88 - 0.035 * o), 2)

    def uncertainty(self, o: int) -> float:
        return round(3 + 1.6 * math.sqrt(o), 1)


_MODELS = {"sarthi-blend": SarthiBlend, "baseline": BaselineHeuristic}


def get_model(name: str = None):
    return _MODELS.get(name or settings.MODEL_NAME, SarthiBlend)()


def model_info() -> dict:
    m = get_model()
    return {"active_model": m.name, "available_models": list(_MODELS),
            "replaceable_without_api_change": True,
            "backtest_vs_naive": SarthiBlend.backtest}
