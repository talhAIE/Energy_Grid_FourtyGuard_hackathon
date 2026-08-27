"""Small, safe client for EIA's API v2 hourly demand route."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from app.core.config import Settings

EIA_SOURCE = "EIA"
EIA_PAGE_SIZE = 5_000
EIA_MAX_PAGES = 100


class EiaError(Exception):
    """Base error with a safe, user-facing message."""


class EiaConfigurationError(EiaError):
    """Raised when required non-secret EIA configuration is missing or invalid."""


class EiaValidationError(EiaError):
    """Raised when a requested EIA import/query range is invalid."""


class EiaRequestError(EiaError):
    """Raised when the EIA service cannot be reached or rejects a request."""


class EiaResponseError(EiaError):
    """Raised when the EIA response does not match the expected data shape."""


@dataclass(frozen=True)
class NormalizedDemandRecord:
    """One validated observation ready for persistence in UTC."""

    period_utc: datetime
    source: str
    source_area_code: str
    demand_mw: Decimal
    is_actual: bool
    quality_flag: str | None


def validate_date_range(
    *, start: datetime, end: datetime, max_days: int
) -> tuple[datetime, datetime]:
    """Normalize an inclusive EIA query range to UTC and keep imports bounded."""
    normalized_start = ensure_utc(start)
    normalized_end = ensure_utc(end)
    if normalized_end <= normalized_start:
        raise EiaValidationError("End time must be later than start time.")
    if normalized_end - normalized_start > timedelta(days=max_days):
        raise EiaValidationError(f"Date range cannot exceed {max_days} days.")
    return normalized_start, normalized_end


def ensure_utc(value: datetime) -> datetime:
    """Interpret a naive API input as UTC and otherwise convert it to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class EiaClient:
    """Fetch and normalize EIA Form 930 hourly balancing-authority demand records."""

    def __init__(self, settings: Settings) -> None:
        if not settings.eia_api_key:
            raise EiaConfigurationError(
                "EIA_API_KEY is not configured. Add it to backend/.env before "
                "importing demand data."
            )
        if not settings.eia_demand_route.strip() or not settings.eia_demand_area_code.strip():
            raise EiaConfigurationError("EIA demand route and area code must be configured.")
        try:
            self._source_timezone = ZoneInfo(settings.eia_source_timezone)
        except ZoneInfoNotFoundError as exc:
            raise EiaConfigurationError(
                "EIA_SOURCE_TIMEZONE must be a valid IANA timezone."
            ) from exc

        self._api_key = settings.eia_api_key
        self._base_url = settings.eia_base_url.rstrip("/")
        self._route = settings.eia_demand_route.strip().strip("/")
        self._area_code = settings.eia_demand_area_code.strip().upper()
        self._demand_type = settings.eia_demand_type.strip().upper()
        self._timeout = settings.eia_request_timeout_seconds

    @property
    def area_code(self) -> str:
        """Configured EIA balancing-authority/area code without exposing credentials."""
        return self._area_code

    def fetch_hourly_demand(
        self, *, start: datetime, end: datetime
    ) -> list[NormalizedDemandRecord]:
        """Fetch every page for the configured area and return valid hourly demand data."""
        params = self._request_params(start=start, end=end)
        records: list[NormalizedDemandRecord] = []
        offset = 0

        with httpx.Client(timeout=httpx.Timeout(self._timeout)) as client:
            for _ in range(EIA_MAX_PAGES):
                page_params = {**params, "offset": offset}
                payload = self._request_page(client=client, params=page_params)
                page = self._extract_rows(payload)
                records.extend(self._normalize_row(row) for row in page)

                if len(page) < EIA_PAGE_SIZE:
                    break
                offset += EIA_PAGE_SIZE
            else:
                raise EiaResponseError("EIA response exceeded the safe pagination limit.")

        return self._deduplicate(records)

    def _request_params(self, *, start: datetime, end: datetime) -> dict[str, str | int]:
        return {
            "api_key": self._api_key,
            "frequency": "hourly",
            "data[0]": "value",
            "facets[respondent][]": self._area_code,
            "facets[type][]": self._demand_type,
            "start": start.strftime("%Y-%m-%dT%H"),
            "end": end.strftime("%Y-%m-%dT%H"),
            "length": EIA_PAGE_SIZE,
            "sort[0][column]": "period",
            "sort[0][direction]": "asc",
        }

    def _request_page(
        self,
        *,
        client: httpx.Client,
        params: dict[str, str | int],
    ) -> dict[str, Any]:
        try:
            response = client.get(f"{self._base_url}/{self._route}", params=params)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise EiaRequestError("EIA request timed out. Please retry the import.") from exc
        except httpx.HTTPStatusError as exc:
            raise EiaRequestError(
                f"EIA rejected the request (HTTP {exc.response.status_code}). "
                "Check the local EIA configuration."
            ) from exc
        except httpx.HTTPError as exc:
            raise EiaRequestError("EIA request failed. Please retry the import.") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise EiaResponseError("EIA returned an unreadable response.") from exc
        if not isinstance(payload, dict):
            raise EiaResponseError("EIA returned an unexpected response format.")
        return payload

    @staticmethod
    def _extract_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
        response = payload.get("response")
        if not isinstance(response, dict):
            raise EiaResponseError("EIA response did not contain a data section.")
        rows = response.get("data")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise EiaResponseError("EIA response did not contain demand records.")
        return rows

    def _normalize_row(self, row: dict[str, Any]) -> NormalizedDemandRecord:
        period_value = row.get("period")
        value = row.get("value")
        if not isinstance(period_value, str):
            raise EiaResponseError("An EIA demand record is missing its period.")
        try:
            demand_mw = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise EiaResponseError("An EIA demand record has an invalid demand value.") from exc
        if not demand_mw.is_finite() or demand_mw < 0:
            raise EiaResponseError("An EIA demand record has an invalid demand value.")

        source_type = str(row.get("type") or self._demand_type).upper()
        quality_value = row.get("quality_flag") or row.get("quality") or row.get("status")
        quality_flag = str(quality_value) if quality_value is not None else None
        return NormalizedDemandRecord(
            period_utc=self._parse_period(period_value),
            source=EIA_SOURCE,
            source_area_code=str(row.get("respondent") or self._area_code).upper(),
            demand_mw=demand_mw,
            is_actual=source_type == "D",
            quality_flag=quality_flag,
        )

    def _parse_period(self, value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise EiaResponseError("An EIA demand record has an invalid timestamp.") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=self._source_timezone)
        return parsed.astimezone(UTC)

    @staticmethod
    def _deduplicate(records: list[NormalizedDemandRecord]) -> list[NormalizedDemandRecord]:
        by_period: dict[datetime, NormalizedDemandRecord] = {}
        for record in records:
            by_period[record.period_utc] = record
        return [by_period[period] for period in sorted(by_period)]
