from fastapi import APIRouter

from slotline.api.v1 import api_keys, auth, health, me, users

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(me.router)
router.include_router(api_keys.router)
router.include_router(users.router)
