from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.deps import get_db_session, get_session_factory
from backend.app.schemas.pledge import (
    PublicComparison,
    PublicPartyScorecard,
    PublicScorecard,
    ScorecardWindow,
)
from backend.app.scoring import DEFAULT_METHODOLOGY, HolderRole
from backend.app.services import PublicPoliticianQueryService
from backend.app.services.party_scorecard_service import (
    AGGREGATION,
    ComparisonValidationError,
    PartyNotFoundError,
    PartyScorecardService,
)
from backend.app.services.pledge_service import PledgeService


router = APIRouter(tags=["scorecards"])


@router.get("/politicians/{politician_id}/scorecard", response_model=PublicScorecard)
def get_politician_scorecard(
    politician_id: Annotated[int, Path(gt=0)],
    session: Annotated[Session, Depends(get_db_session)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    as_of: Annotated[date | None, Query()] = None,
) -> PublicScorecard:
    if PublicPoliticianQueryService(session).get(politician_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="published politician not found",
        )
    return PledgeService(session_factory).scorecard_for_politician(politician_id, as_of=as_of)


@router.get(
    "/political-parties/{party_id}/scorecard", response_model=PublicPartyScorecard
)
def get_party_scorecard(
    party_id: Annotated[int, Path(gt=0)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    window: ScorecardWindow = ScorecardWindow.ALL,
    as_of: Annotated[date | None, Query()] = None,
) -> PublicPartyScorecard:
    try:
        return PartyScorecardService(session_factory).scorecard_for_party(
            party_id, window=window, as_of=as_of
        )
    except PartyNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="political party not found"
        ) from None


@router.get("/compare/politicians", response_model=PublicComparison)
def compare_politicians(
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    ids: Annotated[str, Query(min_length=3, max_length=100, pattern=r"^\d+(,\d+)*$")],
    role: HolderRole,
    as_of: Annotated[date | None, Query()] = None,
) -> PublicComparison:
    """Compare politicians inside one role stratum. There is no cross-role ranking."""

    try:
        return PartyScorecardService(session_factory).compare_politicians(
            [int(item) for item in ids.split(",")], role=role, as_of=as_of
        )
    except ComparisonValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from None
    except PartyNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from None


@router.get("/methodology/scoring")
def get_scoring_methodology() -> dict:
    """Machine-readable summary; the full text is docs/scoring-methodology.md."""

    methodology = DEFAULT_METHODOLOGY
    return {
        "version": methodology.version,
        "formula": "(kept + partial_weight * partially_kept) / closed",
        "partial_weight": methodology.partial_weight,
        "denominator": "closed pledges only (kept, partially_kept, broken)",
        "stratified_by": "holder_role at the time of the pledge; strata are never mixed",
        "excluded": "pledges classified as vague",
        "min_closed_for_rate": methodology.min_closed_for_rate,
        "interval": {
            "type": "beta-binomial equal-tailed credible interval",
            "prior": [methodology.prior_alpha, methodology.prior_beta],
            "level": methodology.credible_level,
        },
        "party_aggregation": AGGREGATION,
        "comparison": "only inside one role stratum, with intervals; no cross-role ranking",
        "review": {
            "approvals_required": {"broken": 2, "other": 1},
            "evidence": "verbatim excerpt from a stored official document",
        },
    }
