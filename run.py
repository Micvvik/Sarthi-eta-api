"""Entry point: python3 run.py  (or: uvicorn app.main:app --host 0.0.0.0 --port 8100)"""
import uvicorn

from app.config import settings

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, log_level="info")
