# SARTHI-ETA — Real-Time Dynamic Train ETA API (MVP)

**SIH26028 · Team TURTLEs (AVV.HDD.001)** — demo configuration of a scalable API that
dynamically predicts train ETAs at upcoming stations and the destination by combining
**real-time running data + historical patterns + network conditions + contextual factors**,
not just schedule + current delay.

Built per `Real_Time_Dynamic_Train_ETA_API_Development_Prompt.pdf`. Because live IR GPS/ops
feeds are not public, this MVP runs on a **mock simulator over real historical sectional
delay profiles** (DA323 public dataset, 42 trains, Mar 2023–Mar 2024). Real RTIS/NTES feeds
plug in later behind the same `/api/v1` contract — no redesign (spec §20).

---

## Quickstart

```bash
cd sih26028_api
pip install -r requirements.txt
python3 run.py                      # serves on http://0.0.0.0:8100
```

* Swagger/OpenAPI docs → `http://localhost:8100/docs`
* Live demo dashboard  → `http://localhost:8100/`
* Run tests (13) → `python3 -m pytest tests/ -q`

## The 10:30 demo (spec §20)

The **hero train** starts on time — destination predicted at **10:30** with high confidence.
Then, on the scripted timeline:

| t (real s) | event                         | effect on predicted arrival |
|-----------:|-------------------------------|-----------------------------|
| 0          | clear run                     | **10:30** (on schedule)     |
| ~20        | CONGESTION (+6 min)           | jumps to ~10:40             |
| ~45        | TSR 30 km/h (+5 min)          | slips further (~10:41–10:46)|

Every new operational datapoint triggers continuous re-prediction (spec §3C) — watch
`GET /api/v1/trains/{hero}/eta` or the dashboard. Restart the demo any time:
`POST /api/v1/simulator/start`.

## API surface (spec §8)

| Area        | Endpoint                                       | Auth |
|-------------|------------------------------------------------|------|
| Trains      | `GET /api/v1/trains`                           | –    |
|             | `GET /api/v1/trains/{no}` · `/live` · `/eta` · `/route` | – |
| Stations    | `GET /api/v1/stations/{code}` · `/arrivals` · `/departures` | – |
| Predictions | `POST /api/v1/predictions`                     | –    |
|             | `GET /api/v1/predictions/{no}` · `/{no}/history` | –  |
| Ingestion   | `POST /api/v1/data/gps` · `/operations` · `/weather` · `/actual-arrival` | `X-API-Key` |
| Simulator   | `POST /api/v1/simulator/start` · `/stop` · `GET /status` | – |
| System      | `GET /api/v1/health` · `/metrics` · `/model`   | –    |

Sample requests/responses: [`docs/api_samples.md`](docs/api_samples.md).
Architecture: [`docs/architecture.svg`](docs/architecture.svg).

## Prediction methodology

**Baseline concept (spec §6):**
`Predicted ETA = now + remaining sectional travel + station dwell + expected operational delay − expected recoverable delay`

**Active model — `sarthi-blend`** (modular, swappable via `MODEL_NAME`, spec §11):

1. **Observed state**: current delay `d0` from live feed (simulated RTIS in demo).
2. **Near horizon (≤3 sections)**: walk learned per-section delay-growth medians (SEC book).
3. **Far horizon**: historical offset-drift curve (OFF medians by horizon).
4. **Gating**: with no observed disruption the schedule is the best estimate; once a
   disruption is observed the drift curve projects compounding.
5. **Confidence/uncertainty**: horizon-decayed confidence (0.95 → 0.55), uncertainty
   `2 + 1.1·√horizon` min, calibrated against back-test error growth.
6. **Historical learning (spec §3D)**: every snapshot + actual station pass is stored;
   `GET /predictions/{no}/history` reports predicted-vs-actual errors and running MAE.

Back-test on DA323 (42 trains, leave-one-train-out):

| Horizon | Naive MAE | SARTHI MAE | Gain |
|---------|----------:|-----------:|-----:|
| Near    | 17.7 min  | 13.6 min   | −23% |
| Mid     | 37.8 min  | 29.7 min   | −21% |
| Far     | 106.2 min | 99.1 min   | −7%  |

## Design notes vs the spec

* **Database (spec §10)** — demo keeps the same table layout in RAM (`app/store.py`):
  trains, stations, train_routes, live_train_positions, eta_predictions, actual_movements,
  operational_events. SQLAlchemy/PostgreSQL is a mechanical swap for Phase 4.
* **Errors (spec §13)** — structured `{"error": {"code", "message"}}`, 404 TRAIN_NOT_FOUND /
  STATION_NOT_FOUND, 401 missing key, 422 validation, 429 rate limit (in-memory limiter).
* **Security (spec §12)** — ingestion endpoints behind `X-API-Key` (demo key
  `sarthi-demo-key`, override via `INGEST_API_KEY` env); config via environment only.
* **Timezone-aware** IST (+05:30) timestamps throughout (spec §11).
* **Continuous updating (spec §3C)** — predictions recompute on every request tick and on
  ingested GPS/ops/weather data.

## Phases (spec §18)

| Phase | Status |
|-------|--------|
| 1 — MVP (routes, live API, ETA engine, Swagger, simulator) | ✅ this build |
| 2 — Dynamic prediction (congestion/TSR/weather recalculation) | ✅ scripted + ingest-driven |
| 3 — ML (XGBoost/LightGBM pipeline, model registry, versioning) | next — engine interface already model-swappable |
| 4 — Production (PostgreSQL, Redis, Kafka, workers, K8s) | architecture-ready |

## Tests (spec §16)

`tests/test_api.py` — 13 integration tests: endpoint contracts, spec §20 10:30 demo
invariant, auth 401, validation 422, simulator start/stop, prediction store/history.

## Deliverable map (spec §17)

| Deliverable | Where |
|---|---|
| Backend API | `app/main.py` |
| Database models | `app/store.py` (+ `app/data.py`) |
| ETA prediction engine | `app/engine.py` |
| Mock simulator | `app/sim.py` |
| Sample dataset | `sample_data/network.json` (built from DA323 by `scripts/build_sample_data.py`) |
| API authentication | `X-API-Key` on `/api/v1/data/*` |
| API + Swagger docs | `/docs`, `docs/api_samples.md` |
| Unit/integration tests | `tests/test_api.py` |
| .env.example | `.env.example` |
| README + setup | this file |
| Sample requests/responses | `docs/api_samples.md` |
| Architecture diagram | `docs/architecture.svg` |
| Methodology explanation | section above |
| Docker / migrations / load tests | Phase 4 scope (noted in spec §9 stack) |
