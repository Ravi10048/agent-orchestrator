"""Error envelope + exception handlers (LLD 09). Every error response has the exact shape
`{"error": {"code", "message", "details"}}` so the frontend can render uniformly."""
from typing import Any

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.channels.base import ChannelNotConfigured
from app.core.config import settings
from app.runtime.executor import GraphValidationError
from app.runtime.scheduler import ScheduleConfigError

_HTTP_CODES = {400: "bad_request", 401: "unauthorized", 403: "forbidden",
               404: "not_found", 405: "method_not_allowed", 409: "conflict"}


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class AppError(Exception):
    status = 500
    code = "internal"

    def __init__(self, message: str = "", details: Any = None):
        self.message = message or self.code
        self.details = details
        super().__init__(self.message)


class BadRequest(AppError):
    status = 400
    code = "bad_request"


class ResourceNotFound(AppError):
    status = 404
    code = "not_found"


class ConflictError(AppError):
    status = 409
    code = "conflict"


def _resp(status: int, code: str, message: str, details: Any = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": jsonable_encoder(details)}},
    )


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_request, exc: AppError):
        return _resp(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(GraphValidationError)
    async def _graph(_request, exc: GraphValidationError):
        return _resp(400, "graph_invalid", "graph validation failed", exc.errors)

    @app.exception_handler(ScheduleConfigError)
    async def _schedule(_request, exc: ScheduleConfigError):
        return _resp(400, "schedule_invalid", str(exc))

    @app.exception_handler(ChannelNotConfigured)
    async def _channel(_request, exc: ChannelNotConfigured):
        return _resp(409, "channel_unconfigured", str(exc))

    @app.exception_handler(RequestValidationError)
    async def _validation(_request, exc: RequestValidationError):
        return _resp(422, "validation_error", "request validation failed", exc.errors())

    @app.exception_handler(StarletteHTTPException)
    async def _http(_request, exc: StarletteHTTPException):
        # framework routing errors (unknown path → 404, wrong method → 405) use the envelope too
        code = _HTTP_CODES.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else "http error"
        return _resp(exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def _unhandled(_request, exc: Exception):
        message = f"{type(exc).__name__}: {exc}" if settings.DEBUG else "internal server error"
        return _resp(500, "internal", message)
