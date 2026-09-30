#!/usr/bin/env python3
"""Build sample_data/network.json from the public DA323 Indian Railways delay dataset.

Output is a self-contained network snapshot: trains, routes, station metadata,
historical per-station delay profiles, learned sectional-delay medians (SEC) and
horizon-offset drift medians (OFF) used by the SARTHI blend prediction model.
"""
import csv, glob, hashlib, json
from collections import defaultdict
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
SRC = sorted(glob.glob(str(ROOT.parent / "sih26028" / "data" / "DA323_*" / "Dataset" / "Train_Route" / "*.csv")))
LIST = ROOT.parent / "sih26028" / "data" / "DA323_*" / "Dataset" / "Train_List.csv"
OUT = ROOT / "sample_data" / "network.json"

CORRIDOR = {"origin": [22.5833, 88.3667], "dest": [26.1833, 91.7500]}  # KOAA -> GHY arc


def hsh(s: str) -> int:
    return int(hashlib.md5(s.encode()).hexdigest(), 16)


def main() -> None:
    names = {}
    for f in glob.glob(str(LIST)):
        for r in csv.DictReader(open(f)):
            names[r["Train_Number"].strip()] = {
                "name": r["Train_Name"].strip(),
                "from": r["From_Station"].strip(),
                "to": r["To_Station"].strip(),
                "type": r["Type"].strip(),
            }

    trains = {}
    for f in SRC:
        rows = list(csv.DictReader(open(f)))
        codes = [r["Station"].strip() for r in rows]
        stnames = [r["Station_Name"].strip() for r in rows]
        delays = [float(r["Average_Delay(min)"]) for r in rows]
        if 10 <= len(delays) <= 40:
            no = Path(f).stem
            meta = names.get(no, {"name": f"TRAIN {no}", "from": codes[0], "to": codes[-1], "type": "Mail/Express"})
            trains[no] = {"number": no, "meta": meta, "codes": codes, "names": stnames, "hist": delays}
    if len(trains) < 6:
        raise SystemExit("not enough trains found in dataset")
    keep = list(trains)[:6]

    # learned historical book: sectional delay growth + horizon offset medians
    sec_map, off_map = defaultdict(list), defaultdict(list)
    for t in trains.values():  # learn from ALL trains, serve 6
        d, c = t["hist"], t["codes"]
        for i in range(len(d) - 1):
            sec_map[f"{c[i]}>{c[i+1]}"].append(d[i + 1] - d[i])
        for k in range(len(d)):
            for j in range(k + 1, min(len(d), k + 18)):
                off_map[j - k].append(d[j] - d[k])
    SEC = {k: round(median(v), 2) for k, v in sec_map.items()}
    OFF = {str(k): round(median(v), 2) for k, v in off_map.items()}

    # synthetic demo schedule + geometry (deterministic)
    out_trains = []
    stations = {}
    for no in keep:
        t = trains[no]
        run, sched, dist = [], [0], [0.0]
        for i in range(len(t["codes"]) - 1):
            r = 14 + hsh(t["codes"][i] + t["codes"][i + 1]) % 22      # 14-35 min running
            halt = 2 + hsh(t["codes"][i + 1]) % 4
            km = round(r * (52 + hsh(t["codes"][i]) % 16) / 60, 1)    # ~52-67 km/h
            run.append(r)
            sched.append(sched[-1] + r + halt)
            dist.append(dist[-1] + km)
        for j, c in enumerate(t["codes"]):
            frac = sched[j] / sched[-1]
            lat = CORRIDOR["origin"][0] + (CORRIDOR["dest"][0] - CORRIDOR["origin"][0]) * frac + (hsh(c) % 40 - 20) / 220
            lon = CORRIDOR["origin"][1] + (CORRIDOR["dest"][1] - CORRIDOR["origin"][1]) * frac + (hsh(c + "x") % 40 - 20) / 220
            stations[c] = {"code": c, "name": t["names"][j], "latitude": round(lat, 4), "longitude": round(lon, 4)}
        out_trains.append({
            "number": no, "name": t["meta"]["name"], "type": t["meta"]["type"],
            "route": [{"seq": j, "code": c, "name": t["names"][j],
                       "sched_offset_min": sched[j], "distance_km": dist[j],
                       "hist_delay_min": t["hist"][j]} for j, c in enumerate(t["codes"])],
            "run_min": run,
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    json.dump({"corridor": CORRIDOR, "stations": stations, "trains": out_trains,
               "sec": SEC, "off": OFF, "source": "DA323 public IR delay dataset (42 trains, Mar23-Mar24)"},
              open(OUT, "w"), indent=1)
    print(f"wrote {OUT} — {len(out_trains)} demo trains, {len(stations)} stations, "
          f"{len(SEC)} sections, {len(OFF)} horizons")


if __name__ == "__main__":
    main()
