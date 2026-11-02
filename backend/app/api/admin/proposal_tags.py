from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.deps import get_admin_principal, get_session_factory
from backend.app.schemas import AdminPrincipal, ProposalTagsRequest, PublicProposalTag
from backend.app.services.proposal_tag_service import (
    ProposalTagNotFoundError,
    ProposalTagService,
    ProposalTagValidationError,
)


router = APIRouter(prefix="/proposals", tags=["admin-proposal-tags"])


@router.put("/{proposal_id}/tags", response_model=tuple[PublicProposalTag, ...])
def replace_proposal_tags(
    proposal_id: Annotated[int, Path(gt=0)],
    payload: ProposalTagsRequest,
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    principal: Annotated[AdminPrincipal, Depends(get_admin_principal)],
) -> tuple[PublicProposalTag, ...]:
    """Replace the controlled tags of a proposal (topics are CAP major codes)."""

    try:
        return ProposalTagService(session_factory).replace(
            proposal_id,
            topics=payload.topics,
            dossiers=payload.dossiers,
            assigned_by=principal.reviewer_identity,
        )
    except ProposalTagNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except ProposalTagValidationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
