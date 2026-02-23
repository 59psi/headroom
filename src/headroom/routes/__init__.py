from fastapi import APIRouter

from headroom.routes.cases import router as cases_router
from headroom.routes.hats import router as hats_router
from headroom.routes.health import router as health_router
from headroom.routes.meta import router as meta_router
from headroom.routes.rooms import router as rooms_router
from headroom.routes.search import router as search_router
from headroom.routes.settings import router as settings_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(cases_router)
api_router.include_router(hats_router)
api_router.include_router(rooms_router)
api_router.include_router(meta_router)
api_router.include_router(search_router)
api_router.include_router(settings_router)
