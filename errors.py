"""Spec §13 error handling — standard HTTP codes, structured error body."""
from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def register(app) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status, content=body(exc.code, exc.message))

    @app.exception_handler(422)
    async def _validation(_: Request, exc):
        return JSONResponse(status_code=422, content=body("VALIDATION_ERROR", str(exc)))

    @app.exception_handler(Exception)
    async def _internal(_: Request, exc: Exception):
        return JSONResponse(status_code=500, content=body("INTERNAL_ERROR", "Unexpected server error."))


TRAIN_NOT_FOUND = lambda no: ApiError(404, "TRAIN_NOT_FOUND", f"The requested train '{no}' could not be found.")
STATION_NOT_FOUND = lambda c: ApiError(404, "STATION_NOT_FOUND", f"The requested station '{c}' could not be found.")
UNAUTHORIZED = ApiError(401, "UNAUTHORIZED", "A valid X-API-Key header is required for data ingestion.")
