# SARTHI-ETA API — Sample Requests & Responses

All responses below were captured live from the running MVP (demo simulator).
Base URL: `http://localhost:8100` · Swagger UI: `/docs`

---

## 1. Train tracking — `GET /api/v1/trains/{train_number}/live`

```bash
curl http://localhost:8100/api/v1/trains/02501/live
```
```json
{
  "train_number": "02501",
  "train_name": "KOAA AGTL SPL",
  "current_position": { "latitude": 25.1061, "longitude": 90.7672 },
  "current_speed_kmph": 63,
  "current_delay_minutes": 5.6,
  "next_station": "NHLG",
  "status": "RUNNING",
  "last_updated": "2026-09-30T08:28:02+05:30"
}
```

## 2. ETA prediction — `GET /api/v1/trains/{train_number}/eta`

All upcoming stations with predicted delay, confidence, uncertainty, causes
(abbreviated to the destination; ~20 s after a scripted CONGESTION event —
note the arrival has moved from 10:30 to 10:39):

```bash
curl http://localhost:8100/api/v1/trains/02501/eta
```
```json
{
  "train_number": "02501",
  "prediction_generated_at": "2026-09-30T08:28:06+05:30",
  "model": "sarthi-blend",
  "predictions": [
    {
      "station_code": "AGTL",
      "station_name": "AGARTALA",
      "scheduled_arrival": "10:30",
      "scheduled_departure": "10:33",
      "predicted_arrival": "10:39",
      "predicted_departure": "10:42",
      "predicted_delay_minutes": 9.2,
      "confidence": 0.78,
      "uncertainty_minutes": 4.7,
      "causes": [
        { "kind": "CONGESTION", "add_minutes": 6,
          "description": "Track congestion ahead of hero train (simulated)" }
      ]
    }
  ]
}
```

## 3. Train list — `GET /api/v1/trains`

```json
{
  "count": 6,
  "sim_time": "2026-09-30T08:28:02+05:30",
  "trains": [
    { "train_number": "02501", "train_name": "KOAA AGTL SPL", "type": "Mail/Express",
      "current_station": "MYD", "current_delay_minutes": 5.6, "status": "RUNNING" },
    { "train_number": "02502", "train_name": "AGTL KOAA SPL", "type": "Superfast",
      "current_station": "NJP", "current_delay_minutes": 0.0, "status": "RUNNING" }
  ]
}
```

Also: `GET /api/v1/trains/{no}` (details), `GET /api/v1/trains/{no}/route`
(full stop sequence with scheduled times, distances, historical delay profile).

## 4. Station APIs

```bash
curl http://localhost:8100/api/v1/stations/AGTL/arrivals
```
Returns every train predicted to arrive within the next 6 h: scheduled vs
predicted arrival ISO timestamps, delay, confidence, status (DUE / AT STN / PASSED).
`/stations/{code}` adds station metadata (name, lat/lon); `/departures` mirrors arrivals.

## 5. Prediction store & evaluation (historical learning, spec §3D)

```bash
curl -X POST http://localhost:8100/api/v1/predictions -d '{"train_number":"02501"}'
curl http://localhost:8100/api/v1/predictions/02501/history
```
```json
{
  "train_number": "02501",
  "snapshots": 3,
  "evaluation": { "n": 3, "mae_min": 5.6 },
  "actual_movements": [ { "station": "MYD", "scheduled_arrival": "...",
                          "actual_arrival": "...", "delay_min": 4.9, "error_min": -1.3 } ],
  "history": [ ... per-snapshot station predictions with error once actuals land ... ]
}
```

## 6. Ingestion (API-key protected, spec §12)

```bash
# without key -> 401
curl -X POST http://localhost:8100/api/v1/data/gps \
  -d '{"train_number":"02501","latitude":25,"longitude":89,"speed_kmph":70}'
```
```json
{ "error": { "code": "UNAUTHORIZED",
             "message": "A valid X-API-Key header is required for data ingestion." } }
```
```bash
# with key -> accepted, ETA recalculates on next request (continuous updating)
curl -X POST http://localhost:8100/api/v1/data/operations \
  -H 'X-API-Key: sarthi-demo-key' -H 'Content-Type: application/json' \
  -d '{"train_number":"02501","kind":"BLOCK","add_minutes":4,
       "description":"Maintenance block ingested via API"}'
```
```json
{ "status": "accepted", "event": "BLOCK" }
```
Same pattern for `/data/weather` (`condition`, `visibility_m`, `add_minutes`)
and `/data/actual-arrival` (`station_code`, `actual_delay_minutes`).

## 7. Error handling (spec §13)

```bash
curl http://localhost:8100/api/v1/trains/99999
```
```json
{ "error": { "code": "TRAIN_NOT_FOUND",
             "message": "The requested train '99999' could not be found." } }
```
Codes used: 200 · 401 · 404 (TRAIN_NOT_FOUND / STATION_NOT_FOUND) ·
422 (validation) · 429 (rate limit, 300 req/min/IP) · 500.

## 8. Simulator control (spec §14)

```bash
curl -X POST http://localhost:8100/api/v1/simulator/start   # reset + restart the 10:30 demo
curl -X POST http://localhost:8100/api/v1/simulator/stop
curl http://localhost:8100/api/v1/simulator/status
```
Status includes sim clock, hero-train demo summary (scheduled vs predicted
destination arrival), fired events, and pending scripted events with fire times.

## 9. System

* `GET /api/v1/health` — liveness, model name, sim clock
* `GET /api/v1/metrics` — trains tracked, snapshots stored, actuals recorded, MAE by train
* `GET /api/v1/model` — active model, available models, back-test vs naive
