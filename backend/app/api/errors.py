from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.app.schemas import APIErrorDetail, APIErrorResponse
from backend.app.services import (
    DraftNotFoundError,
    DraftNotReviewableError,
    InvalidDraftError,
    PublishConflictError,
    PublishPersistenceError,
    PublishServiceError,
    ReviewConflictError,
    ReviewInputError,
    ReviewPersistenceError,
    ReviewServiceError,
    StaleDraftError,
)


def error_response(
    status_code: int,
    *,
    code: str,
    message: str,
    details=None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    payload = APIErrorResponse(
        error=APIErrorDetail(code=code, message=message, details=details)
    )
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(payload.model_dump(mode="json")),
        headers=headers,
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        del request
        codes = {
            status.HTTP_401_UNAUTHORIZED: "unauthorized",
            status.HTTP_404_NOT_FOUND: "not_found",
            status.HTTP_422_UNPROCESSABLE_CONTENT: "validation_error",
            status.HTTP_503_SERVICE_UNAVAILABLE: "service_unavailable",
        }
        return error_response(
            exc.status_code,
            code=codes.get(exc.status_code, "http_error"),
            message=str(exc.detail),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request,
        exc: RequestValidationError,
    ):
        del request
        return error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="validation_error",
            message="request validation failed",
            details=jsonable_encoder(exc.errors()),
        )

    async def not_found_handler(request: Request, exc: Exception):
        del request
        return error_response(
            status.HTTP_404_NOT_FOUND,
            code="draft_not_found",
            message=str(exc),
        )

    async def conflict_handler(request: Request, exc: Exception):
        del request
        return error_response(
            status.HTTP_409_CONFLICT,
            code=_conflict_code(exc),
            message=str(exc),
        )

    async def input_handler(request: Request, exc: Exception):
        del request
        return error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="invalid_review_input",
            message=str(exc),
        )

    async def persistence_handler(request: Request, exc: Exception):
        del request, exc
        return error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="persistence_error",
            message="an internal persistence error occurred",
        )

    async def internal_handler(request: Request, exc: Exception):
        del request, exc
        return error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="internal_error",
            message="an unexpected internal error occurred",
        )

    app.add_exception_handler(DraftNotFoundError, not_found_handler)
    for exception_type in (
        DraftNotReviewableError,
        StaleDraftError,
        InvalidDraftError,
        PublishConflictError,
        ReviewConflictError,
    ):
        app.add_exception_handler(exception_type, conflict_handler)
    app.add_exception_handler(ReviewInputError, input_handler)
    for exception_type in (PublishPersistenceError, ReviewPersistenceError):
        app.add_exception_handler(exception_type, persistence_handler)
    app.add_exception_handler(PublishServiceError, conflict_handler)
    app.add_exception_handler(ReviewServiceError, conflict_handler)
    app.add_exception_handler(Exception, internal_handler)


def _conflict_code(exc: Exception) -> str:
    if isinstance(exc, StaleDraftError):
        return "stale_draft"
    if isinstance(exc, (PublishConflictError, ReviewConflictError)):
        return "decision_conflict"
    if isinstance(exc, InvalidDraftError):
        return "invalid_draft"
    return "draft_not_reviewable"
