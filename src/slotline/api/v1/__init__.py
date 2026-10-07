from fastapi import APIRouter

from slotline.api.v1 import health

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
