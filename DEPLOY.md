# Deploying SARTHI-ETA API to Render (free) — 5-minute guide

Result: a permanent link like `https://sarthi-eta-api.onrender.com` for your PPT.

## Step 1 — GitHub repo (2 min)

1. Sign in at github.com → **+** → **New repository** → name it `sarthi-eta-api`, keep **Public** → **Create**.
2. Put the project files at the repo **root** (so `requirements.txt`, `run.py`, `app/`,
   `sample_data/`, `static/` are top-level — NOT inside a folder).
   * Easiest: have your assistant push it for you (give it a temporary token), or
   * GitHub web: **uploading an existing file** → drag the *contents* of `sih26028_api/`.

## Step 2 — Render service (2 min)

1. render.com → **Get Started for Free** → sign in **with GitHub**.
2. Dashboard → **New → Web Service** → connect your GitHub account → pick `sarthi-eta-api`.
3. Settings:
   * **Name:** `sarthi-eta-api`  (this becomes the URL slug)
   * **Region:** Singapore (closest to India)
   * **Build Command:** `pip install -r requirements.txt`
   * **Start Command:** `python3 run.py`
   * **Instance Type:** **Free**
4. **Create Web Service**. Build takes ~1–2 min; status turns **Live**.

Your link: `https://sarthi-eta-api.onrender.com`
* Demo dashboard → `https://sarthi-eta-api.onrender.com/`
* Swagger docs → `https://sarthi-eta-api.onrender.com/docs`

## Notes

* Free tier sleeps after ~15 min idle: first click takes 30–60 s to wake it.
  **Click the link once before your presentation** so it's warm for judges.
* The simulator restarts on each cold start — that's fine: the 10:30 demo replays
  fresh (CONGESTION ~20 s, TSR ~45 s).
* `PORT` is injected by Render automatically; the app reads it (no config needed).

## In your PPT

> **Prototype (live):** https://sarthi-eta-api.onrender.com — Swagger API docs at /docs
