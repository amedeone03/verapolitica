from fastapi import APIRouter, Depends

from backend.app.api.admin.drafts import router as drafts_router
from backend.app.api.deps import require_admin


router = APIRouter(
    prefix="/admin",
    dependencies=[Depends(require_admin)],
)
router.include_router(drafts_router)

__all__ = ["router"]
