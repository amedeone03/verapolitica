from fastapi import APIRouter

from backend.app.api.public.politicians import router as politicians_router
from backend.app.api.public.proposals import router as proposals_router


router = APIRouter()
router.include_router(politicians_router)
router.include_router(proposals_router)

__all__ = ["router"]
