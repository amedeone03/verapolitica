from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.app.schemas import APIErrorDetail, APIErrorResponse
from backend.app.services import (
    DraftNotFoundError,
    DraftNotReviewableError,
    InvalidDraftError,
    IdentityResolutionCaseNotFoundError,
    IdentityResolutionConflictError,
    IdentityResolutionInputError,
    IdentityResolutionPersistenceError,
    IdentityResolutionServiceError,
    IdentityResolutionStateError,
    PublishConflictError,
    PublishPersistenceError,
    PublishServiceError,
    ReviewConflictError,
    ReviewInputError,
    ReviewPersistenceError,
    ReviewServiceError,
    StaleDraftError,
    ProposalDraftNotFoundError,
    ProposalDraftNotReviewableError,
    ProposalDraftStaleError,
    ProposalReviewConflictError,
    ProposalReviewPersistenceError,
    ProposalReviewServiceError,
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

    async def proposal_not_found_handler(request: Request, exc: Exception):
        del request
        return error_response(
            status.HTTP_404_NOT_FOUND,
            code="proposal_draft_not_found",
            message=str(exc),
        )

    async def proposal_conflict_handler(request: Request, exc: Exception):
        del request
        code = (
            "stale_proposal_draft"
            if isinstance(exc, ProposalDraftStaleError)
            else "proposal_draft_not_reviewable"
        )
        return error_response(
            status.HTTP_409_CONFLICT,
            code=code,
            message=str(exc),
        )

    app.add_exception_handler(ProposalDraftNotFoundError, proposal_not_found_handler)
    for exception_type in (
        ProposalDraftNotReviewableError,
        ProposalDraftStaleError,
        ProposalReviewConflictError,
        ProposalReviewServiceError,
    ):
        app.add_exception_handler(exception_type, proposal_conflict_handler)
    app.add_exception_handler(ProposalReviewPersistenceError, persistence_handler)

    async def identity_not_found_handler(request: Request, exc: Exception):
        del request
        return error_response(
            status.HTTP_404_NOT_FOUND,
            code="identity_resolution_not_found",
            message=str(exc),
        )

    async def identity_input_handler(request: Request, exc: Exception):
        del request
        return error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="invalid_identity_resolution_input",
            message=str(exc),
        )

    async def identity_conflict_handler(request: Request, exc: Exception):
        del request
        return error_response(
            status.HTTP_409_CONFLICT,
            code="identity_resolution_conflict",
            message=str(exc),
        )

    app.add_exception_handler(
        IdentityResolutionCaseNotFoundError, identity_not_found_handler
    )
    app.add_exception_handler(IdentityResolutionInputError, identity_input_handler)
    app.add_exception_handler(IdentityResolutionStateError, identity_conflict_handler)
    app.add_exception_handler(
        IdentityResolutionConflictError, identity_conflict_handler
    )
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
    app.add_exception_handler(IdentityResolutionPersistenceError, persistence_handler)
    app.add_exception_handler(PublishServiceError, conflict_handler)
    app.add_exception_handler(ReviewServiceError, conflict_handler)
    app.add_exception_handler(IdentityResolutionServiceError, identity_conflict_handler)
    app.add_exception_handler(Exception, internal_handler)


def _conflict_code(exc: Exception) -> str:
    if isinstance(exc, StaleDraftError):
        return "stale_draft"
    if isinstance(exc, (PublishConflictError, ReviewConflictError)):
        return "decision_conflict"
    if isinstance(exc, InvalidDraftError):
        return "invalid_draft"
    return "draft_not_reviewable"
