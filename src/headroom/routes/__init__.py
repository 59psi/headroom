from fastapi import APIRouter

from headroom.routes.admin import router as admin_router
from headroom.routes.auth import router as auth_router
from headroom.routes.cases import router as cases_router
from headroom.routes.hats import router as hats_router
from headroom.routes.health import router as health_router
from headroom.routes.import_jobs import router as import_jobs_router
from headroom.routes.meta import router as meta_router
from headroom.routes.rooms import router as rooms_router
from headroom.routes.search import router as search_router
from headroom.routes.settings import router as settings_router
from headroom.routes.share import router as share_router
from headroom.routes.share_links import router as share_links_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(cases_router)
# import_jobs must register before hats so /api/hats/import isn't shadowed
# by /api/hats/{hat_id} path-parsing.
api_router.include_router(import_jobs_router)
api_router.include_router(hats_router)
api_router.include_router(rooms_router)
api_router.include_router(meta_router)
api_router.include_router(search_router)
api_router.include_router(settings_router)
api_router.include_router(admin_router)
api_router.include_router(share_router)
api_router.include_router(share_links_router)
