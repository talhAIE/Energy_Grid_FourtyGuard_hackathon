from fastapi import APIRouter

from app.api.v1.data import router as data_router
from app.api.v1.health import router as health_router
from app.api.v1.heatmaps import router as heatmaps_router
from app.api.v1.zones import router as zones_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(data_router, prefix="/data", tags=["demand data"])
api_router.include_router(heatmaps_router, prefix="/heatmaps", tags=["heatmaps"])
api_router.include_router(zones_router, prefix="/zones", tags=["zones"])
