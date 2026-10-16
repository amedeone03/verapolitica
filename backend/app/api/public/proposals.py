from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.deps import get_api_settings, get_db_session, get_session_factory
from backend.app.core.config import Settings
from backend.app.models import ProposalStatus, ProposalType
from backend.app.schemas import PublicProposal, PublicProposalList
from backend.app.schemas.pledge import PledgeExplanationResponse
from backend.app.services import PublicProposalQueryService
from backend.app.services.pledge_explanation_service import PledgeExplanationService
from backend.app.services.pledge_service import PledgeNotFoundError


router = APIRouter(prefix="/proposals", tags=["proposals"])


@router.get("", response_model=PublicProposalList)
def list_proposals(
    session: Annotated[Session, Depends(get_db_session)],
    proposal_status: Annotated[ProposalStatus | None, Query(alias="status")] = None,
    proposal_type: ProposalType | None = None,
    politician: Annotated[int | None, Query(gt=0)] = None,
    source: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> PublicProposalList:
    return PublicProposalQueryService(session).list(
        offset=offset,
        limit=limit,
        proposal_status=proposal_status,
        proposal_type=proposal_type,
        politician_id=politician,
        source_key=source,
    )


@router.get("/{proposal_id}", response_model=PublicProposal)
def get_proposal(
    proposal_id: Annotated[int, Path(gt=0)],
    session: Annotated[Session, Depends(get_db_session)],
) -> PublicProposal:
    proposal = PublicProposalQueryService(session).get(proposal_id)
    if proposal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="published proposal not found",
        )
    return proposal


@router.get("/{proposal_id}/explanation", response_model=PledgeExplanationResponse)
def explain_proposal(
    proposal_id: Annotated[int, Path(gt=0)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    settings: Annotated[Settings, Depends(get_api_settings)],
) -> PledgeExplanationResponse:
    """Read-only citizen explanation of a published pledge assessment."""

    try:
        return PledgeExplanationService(session_factory, settings).explain(proposal_id)
    except PledgeNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="published proposal not found",
        ) from None
