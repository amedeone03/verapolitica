from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.deps import get_db_session, get_session_factory
from backend.app.schemas.pledge import PublicScorecard
from backend.app.scoring import DEFAULT_METHODOLOGY
from backend.app.services import PublicPoliticianQueryService
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
        "review": {
            "approvals_required": {"broken": 2, "other": 1},
            "evidence": "verbatim excerpt from a stored official document",
        },
    }
