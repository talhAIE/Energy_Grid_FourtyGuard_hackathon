"""Import a bounded EIA historical demand period from the command line."""

import argparse
from datetime import datetime

from app.db.database import get_session_factory
from app.services.demand_data_service import DemandDataNotReadyError, import_eia_demand
from app.services.eia_client import EiaError


def parse_datetime(value: str) -> datetime:
    """Parse an ISO-8601 command-line timestamp, including a trailing Z."""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use ISO-8601, for example 2025-08-01T00:00:00Z.") from exc


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import EIA hourly demand data for the configured area."
    )
    parser.add_argument("--start", required=True, type=parse_datetime)
    parser.add_argument("--end", required=True, type=parse_datetime)
    args = parser.parse_args()

    session_factory = get_session_factory()
    with session_factory() as session:
        try:
            result = import_eia_demand(session=session, start=args.start, end=args.end)
        except (DemandDataNotReadyError, EiaError) as exc:
            raise SystemExit(f"EIA import failed: {exc}") from exc
        print(
            "EIA import finished: "
            f"created={result.created_count}, skipped_duplicates={result.skipped_duplicate_count}, "
            f"fetched={result.fetched_count}, area={result.source_area_code}."
        )


if __name__ == "__main__":
    main()
