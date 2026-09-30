"""Environment-driven configuration (spec §12: secure env vars)."""
import os


class Settings:
    PORT: int = int(os.getenv("PORT", "8100"))
    HOST: str = os.getenv("HOST", "0.0.0.0")

    # Prediction engine is replaceable without changing the public API (spec §11)
    MODEL_NAME: str = os.getenv("MODEL_NAME", "sarthi-blend")  # or "baseline"

    # Simulator clock: SIM_SPEED sim-minutes per real second (2.0 ≈ 120x)
    SIM_SPEED: float = float(os.getenv("SIM_SPEED", "2.0"))
    SECTION_REAL_S: float = float(os.getenv("SECTION_REAL_S", "15.0"))  # real s per section
    SNAPSHOT_REAL_S: float = float(os.getenv("SNAPSHOT_REAL_S", "5.0"))

    # API-key auth for ingestion endpoints (spec §12)
    INGEST_API_KEY: str = os.getenv("INGEST_API_KEY", "sarthi-demo-key")

    # Rate limiting (spec §13: 429)
    RATE_LIMIT_PER_MIN: int = int(os.getenv("RATE_LIMIT_PER_MIN", "300"))

    DEMO_ARRIVAL_HHMM: str = os.getenv("DEMO_ARRIVAL_HHMM", "10:30")  # hero train demo ETA


settings = Settings()
