from fastapi import APIRouter

from app.api.v1.cycles import demo_router
from app.api.v1.cycles import router as cycles_router
from app.api.v1.data import router as data_router
from app.api.v1.forecast import router as forecast_router
from app.api.v1.forecasts import router as forecasts_router
from app.api.v1.health import router as health_router
from app.api.v1.heatmaps import router as heatmaps_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.recommendations import router as recommendations_router
from app.api.v1.temperatures import router as temperatures_router
from app.api.v1.zones import router as zones_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(data_router, prefix="/data", tags=["demand data"])
api_router.include_router(cycles_router, prefix="/cycles", tags=["pipeline cycles"])
api_router.include_router(demo_router, prefix="/demo", tags=["demo"])
api_router.include_router(forecast_router, prefix="/forecast", tags=["forecast"])
api_router.include_router(forecasts_router, prefix="/forecasts", tags=["zone forecasts"])
api_router.include_router(heatmaps_router, prefix="/heatmaps", tags=["heatmaps"])
api_router.include_router(jobs_router, prefix="/jobs", tags=["jobs"])
api_router.include_router(
    recommendations_router,
    prefix="/recommendations",
    tags=["recommendations"],
)
api_router.include_router(temperatures_router, prefix="/temperatures", tags=["temperatures"])
api_router.include_router(zones_router, prefix="/zones", tags=["zones"])
