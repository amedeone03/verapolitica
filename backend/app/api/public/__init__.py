from fastapi import APIRouter

from backend.app.api.public.civic import (
    glossary_router,
    referendums_router,
    voting_guides_router,
)
from backend.app.api.public.municipalities import router as municipalities_router
from backend.app.api.public.organizations import (
    groups_router,
    parties_router,
)
from backend.app.api.public.politicians import router as politicians_router
from backend.app.api.public.portraits import router as portraits_router
from backend.app.api.public.proposals import router as proposals_router
from backend.app.api.public.regions import router as regions_router
from backend.app.api.public.scorecards import router as scorecards_router
from backend.app.api.public.search import router as search_router


router = APIRouter()
router.include_router(search_router)
router.include_router(portraits_router)
router.include_router(politicians_router)
router.include_router(proposals_router)
router.include_router(scorecards_router)
router.include_router(regions_router)
router.include_router(municipalities_router)
router.include_router(groups_router)
router.include_router(parties_router)
router.include_router(referendums_router)
router.include_router(voting_guides_router)
router.include_router(glossary_router)

__all__ = ["router"]
