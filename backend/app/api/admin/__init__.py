from fastapi import APIRouter, Depends

from backend.app.api.admin.drafts import router as drafts_router
from backend.app.api.admin.identity_resolution import (
    router as identity_resolution_router,
)
from backend.app.api.admin.jobs import router as jobs_router
from backend.app.api.admin.proposals import router as proposals_router
from backend.app.api.admin.referendums import router as referendums_router
from backend.app.api.deps import require_admin


router = APIRouter(
    prefix="/admin",
    dependencies=[Depends(require_admin)],
)
router.include_router(drafts_router)
router.include_router(identity_resolution_router)
router.include_router(proposals_router)
router.include_router(referendums_router)
router.include_router(jobs_router)

__all__ = ["router"]
