"""Errors, and how they are turned into HTTP responses.

All error responses use one shape, RFC 9457 "problem details":

    {"type": "about:blank", "title": "Not Found", "status": 404, "detail": "..."}

so that a client needs a single way to read them.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_JSON = "application/problem+json"


class ApiError(Exception):
    status_code = 500
    title = "Internal Server Error"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.title)
        self.detail = detail


class NotFoundError(ApiError):
    """Also used when the thing exists but belongs to another workspace.

    Answering 403 there would confirm that the ID is real.
    """

    status_code = 404
    title = "Not Found"


class UnauthorizedError(ApiError):
    status_code = 401
    title = "Unauthorized"


class ForbiddenError(ApiError):
    status_code = 403
    title = "Forbidden"


class ConflictError(ApiError):
    status_code = 409
    title = "Conflict"


class InvalidRequestError(ApiError):
    status_code = 422
    title = "Unprocessable Content"


class TooManyRequestsError(ApiError):
    status_code = 429
    title = "Too Many Requests"


def problem(status: int, title: str, detail: str | None = None, **extra: object) -> JSONResponse:
    body: dict[str, object] = {"type": "about:blank", "title": title, "status": status}
    if detail:
        body["detail"] = detail
    body.update(extra)
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)


logger = logging.getLogger("paritylens.api")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(Exception)
    async def unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        # Anything nobody anticipated. The client gets a plain 500 in the
        # usual shape; the log gets the exception's type and no message,
        # since messages quote inputs.
        logger.error("unhandled error", extra={"error_type": type(exc).__name__})
        return problem(500, "Internal Server Error")

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return problem(exc.status_code, exc.title, exc.detail)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Raised by the framework itself: unknown route, wrong method.
        return problem(exc.status_code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Where each problem is and what it is, without echoing the input
        # back: a rejected request body may contain a credential.
        errors = [
            {"location": ".".join(str(part) for part in error["loc"]), "message": error["msg"]}
            for error in exc.errors()
        ]
        return problem(422, "Unprocessable Content", "the request is not valid", errors=errors)
