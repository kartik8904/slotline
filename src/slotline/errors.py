"""Problem Details (RFC 9457) errors with stable codes clients can switch on."""

from enum import StrEnum
from typing import Any, cast

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_CONTENT_TYPE = "application/problem+json"
ERROR_TYPE_BASE = "https://slotline.dev/errors/"

log = structlog.get_logger()


class ErrorCode(StrEnum):
    INVALID_REQUEST = "invalid_request"
    UNAUTHENTICATED = "unauthenticated"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    SLOT_UNAVAILABLE = "slot_unavailable"
    INVALID_TRANSITION = "invalid_transition"
    CUSTOMER_EXISTS = "customer_exists"
    TIME_OFF_CONFLICT = "time_off_conflict"
    REQUEST_IN_PROGRESS = "request_in_progress"
    HOLD_EXPIRED = "hold_expired"
    PRECONDITION_FAILED = "precondition_failed"
    VALIDATION_ERROR = "validation_error"
    IDEMPOTENCY_KEY_REUSED = "idempotency_key_reused"
    RATE_LIMITED = "rate_limited"
    INTERNAL_ERROR = "internal_error"
    SERVICE_UNAVAILABLE = "service_unavailable"
    EMAIL_EXISTS = "email_exists"
    LAST_OWNER = "last_owner"


class AppError(Exception):
    """Raise from services or routes; the handler turns it into Problem Details."""

    def __init__(
        self,
        status: int,
        code: ErrorCode,
        title: str,
        detail: str | None = None,
        extra: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail or title)
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.extra = extra or {}
        self.headers = headers or {}


def unauthenticated() -> AppError:
    """One answer for every credential failure, so responses never say which part was wrong."""
    return AppError(
        401,
        ErrorCode.UNAUTHENTICATED,
        "Unauthenticated",
        "Missing, invalid or expired credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def forbidden(detail: str) -> AppError:
    return AppError(403, ErrorCode.FORBIDDEN, "Forbidden", detail)


def not_found(detail: str = "Resource not found.") -> AppError:
    """Also the answer for another tenant's ID: 404, never 403, so existence isn't leaked."""
    return AppError(404, ErrorCode.NOT_FOUND, "Not found", detail)


def field_error(field: str, message: str, error_type: str) -> AppError:
    """A 422 validation_error for a rule only the service can check (for example, a password)."""
    return AppError(
        422,
        ErrorCode.VALIDATION_ERROR,
        "Validation error",
        "One or more fields are invalid.",
        extra={"errors": [{"field": field, "message": message, "type": error_type}]},
    )


def _request_id(request: Request) -> str | None:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else None


def problem_response(
    request: Request,
    status: int,
    code: ErrorCode,
    title: str,
    detail: str | None = None,
    extra: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"{ERROR_TYPE_BASE}{code.value}",
        "title": title,
        "status": status,
        "code": code.value,
    }
    if detail is not None:
        body["detail"] = detail
    request_id = _request_id(request)
    if request_id is not None:
        body["request_id"] = request_id
    body.update(extra or {})
    out_headers = dict(headers or {})
    if request_id is not None:
        # The catch-all handler runs outside our middleware, so set the header here too.
        out_headers["X-Request-ID"] = request_id
    return JSONResponse(
        body, status_code=status, media_type=PROBLEM_CONTENT_TYPE, headers=out_headers
    )


async def _app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    exc = cast(AppError, exc)
    return problem_response(
        request, exc.status, exc.code, exc.title, exc.detail, exc.extra, exc.headers
    )


async def _http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    exc = cast(StarletteHTTPException, exc)
    mapping = {
        400: (ErrorCode.INVALID_REQUEST, "Invalid request"),
        401: (ErrorCode.UNAUTHENTICATED, "Unauthenticated"),
        403: (ErrorCode.FORBIDDEN, "Forbidden"),
        404: (ErrorCode.NOT_FOUND, "Not found"),
        429: (ErrorCode.RATE_LIMITED, "Rate limited"),
    }
    code, title = mapping.get(exc.status_code, (ErrorCode.INVALID_REQUEST, "Request failed"))
    detail = exc.detail if isinstance(exc.detail, str) else None
    return problem_response(
        request, exc.status_code, code, title, detail, headers=dict(exc.headers or {})
    )


async def _validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    exc = cast(RequestValidationError, exc)
    errors = [
        {
            "field": ".".join(str(part) for part in err["loc"]),
            "message": err["msg"],
            "type": err["type"],
        }
        for err in exc.errors()
    ]
    return problem_response(
        request,
        422,
        ErrorCode.VALIDATION_ERROR,
        "Validation error",
        "One or more fields are invalid.",
        extra={"errors": errors},
    )


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled_exception", exc_info=exc)
    return problem_response(
        request, 500, ErrorCode.INTERNAL_ERROR, "Internal error", "Something went wrong."
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
