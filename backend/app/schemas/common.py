from typing import Literal

from pydantic import BaseModel, Field

from app.core.config import get_settings


def current_data_mode() -> Literal["live", "replay"]:
    """Expose the current source mode in API responses without exposing configuration secrets."""
    return "replay" if get_settings().replay_mode else "live"


class DataModeResponse(BaseModel):
    """Base response envelope that makes live versus offline replay data visible to the UI."""

    data_mode: Literal["live", "replay"] = Field(default_factory=current_data_mode)
