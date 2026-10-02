from fastapi import APIRouter

from backend.app.api.public.politicians import router as politicians_router


router = APIRouter()
router.include_router(politicians_router)

__all__ = ["router"]
