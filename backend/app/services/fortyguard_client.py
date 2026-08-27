"""Isolated, credential-safe FortyGuard heatmap submission client."""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings


class FortyGuardError(Exception):
    """Base exception for safe FortyGuard integration failures."""


class FortyGuardConfigurationError(FortyGuardError):
    """Raised when the server-side FortyGuard configuration is incomplete."""


class FortyGuardRequestError(FortyGuardError):
    """Raised when FortyGuard cannot accept or complete the submission request."""

    def __init__(self, message: str, *, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class FortyGuardResponseError(FortyGuardError):
    """Raised when a successful HTTP response lacks a usable activity ID."""


@dataclass(frozen=True)
class HeatmapProviderRequest:
    """Only the safe request fields needed by FortyGuard's heatmap endpoint."""

    polygon_aoi: dict[str, Any]
    date_time: dict[str, str | int]
    granularity: int
    analytic_type: str


@dataclass(frozen=True)
class FortyGuardSubmission:
    """Safe submission acknowledgement returned to the application service."""

    activity_id: str


def build_heatmap_payload(request: HeatmapProviderRequest) -> dict[str, Any]:
    """Build the exact documented provider payload without any credentials."""
    return {
        "polygon_aoi": request.polygon_aoi,
        "date_time": request.date_time,
        "granularity": request.granularity,
        "analytic_type": request.analytic_type,
    }


def canonical_request_hash(request: HeatmapProviderRequest) -> str:
    """Hash canonical JSON so equivalent inputs always share one provider job."""
    canonical_json = json.dumps(
        build_heatmap_payload(request),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class FortyGuardClient:
    """Submit a heatmap task and return immediately after its activity ID is acknowledged."""

    def __init__(self, settings: Settings) -> None:
        if not settings.fortyguard_api_key:
            raise FortyGuardConfigurationError(
                "FORTYGUARD_API_KEY is not configured. Add it to backend/.env "
                "before submitting a heatmap."
            )
        self._api_key = settings.fortyguard_api_key
        self._base_url = settings.fortyguard_base_url.rstrip("/")
        self._timeout = settings.fortyguard_request_timeout_seconds

    def submit_heatmap(self, request: HeatmapProviderRequest) -> FortyGuardSubmission:
        """Submit one task; polling and result retrieval intentionally start in Phase 5."""
        try:
            with httpx.Client(timeout=httpx.Timeout(self._timeout)) as client:
                response = client.post(
                    f"{self._base_url}/v1/heatmap",
                    headers={"api-key": self._api_key, "Content-Type": "application/json"},
                    json=build_heatmap_payload(request),
                )
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise FortyGuardRequestError(
                "FortyGuard submission timed out. The request was not retried "
                "to avoid duplicate work.",
                error_code="timeout",
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise FortyGuardRequestError(
                f"FortyGuard rejected the heatmap submission (HTTP {exc.response.status_code}).",
                error_code=f"http_{exc.response.status_code}",
            ) from exc
        except httpx.HTTPError as exc:
            raise FortyGuardRequestError(
                "FortyGuard submission failed. The request was not retried "
                "to avoid duplicate work.",
                error_code="request_failed",
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise FortyGuardResponseError(
                "FortyGuard returned an unreadable submission response."
            ) from exc
        if not isinstance(payload, dict):
            raise FortyGuardResponseError("FortyGuard returned an unexpected submission response.")
        data = payload.get("data")
        activity_id = data.get("activity_id") if isinstance(data, dict) else None
        if not isinstance(activity_id, str) or not activity_id.strip():
            raise FortyGuardResponseError(
                "FortyGuard did not return an activity ID for the heatmap job."
            )
        return FortyGuardSubmission(activity_id=activity_id.strip())
