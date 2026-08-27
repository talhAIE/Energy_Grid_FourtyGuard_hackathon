from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging


def create_application() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    application = FastAPI(
        title="Energy Grid API",
        version="0.1.0",
        description=(
            "Backend for a human-supervised heat-driven electricity-demand risk forecaster."
        ),
    )
    application.include_router(api_router, prefix=settings.api_v1_prefix)
    return application


app = create_application()

