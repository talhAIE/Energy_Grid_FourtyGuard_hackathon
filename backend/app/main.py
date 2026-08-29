from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.database import DatabaseNotConfiguredError

OPENAPI_TAGS = [
    {"name": "health", "description": "Non-sensitive service and dependency health."},
    {"name": "zones", "description": "Configured demo-zone geometry and allocation weights."},
    {"name": "demand data", "description": "Stored city-level demand data and bounded EIA import."},
    {"name": "heatmaps", "description": "Asynchronous FortyGuard heatmap submission."},
    {"name": "jobs", "description": "Durable one-shot heatmap job status polling."},
    {
        "name": "pipeline cycles",
        "description": "Development/test-only manually advanced pipeline cycles.",
    },
    {
        "name": "forecast",
        "description": "Versioned city-demand forecast and active-model metadata.",
    },
    {
        "name": "zone forecasts",
        "description": "Explainable zone-level proxy demand and risk forecasts.",
    },
    {
        "name": "recommendations",
        "description": "Human-reviewed decision support; never grid control.",
    },
    {"name": "audit", "description": "Read-only, redacted audit history for QA and traceability."},
    {"name": "demo", "description": "Development/test-only offline replay controls."},
]


def create_application() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    application = FastAPI(
        title="Energy Grid API",
        version="0.1.0",
        description=(
            "Backend for a human-supervised heat-driven electricity-demand risk forecaster. "
            "Zone values are proxy estimates, and recommendations never control grid equipment."
        ),
        openapi_tags=OPENAPI_TAGS,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.parsed_cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        max_age=600,
    )
    _register_error_handlers(application)
    application.include_router(api_router, prefix=settings.api_v1_prefix)
    return application


def _register_error_handlers(application: FastAPI) -> None:
    """Keep malformed requests and unavailable local infrastructure safe for API consumers."""

    @application.exception_handler(RequestValidationError)
    async def request_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "code": "invalid_request",
                    "message": "Request validation failed.",
                    "errors": [
                        {
                            "location": list(error["loc"]),
                            "message": error["msg"],
                            "type": error["type"],
                        }
                        for error in exc.errors()
                    ],
                }
            },
        )

    @application.exception_handler(DatabaseNotConfiguredError)
    async def database_not_configured(_: Request, __: DatabaseNotConfiguredError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "detail": {
                    "code": "database_not_configured",
                    "message": (
                        "Database-backed routes are unavailable until DATABASE_URL is configured."
                    ),
                }
            },
        )

    @application.exception_handler(SQLAlchemyError)
    async def database_unavailable(_: Request, __: SQLAlchemyError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "detail": {
                    "code": "database_unavailable",
                    "message": "The database is temporarily unavailable.",
                }
            },
        )


app = create_application()
