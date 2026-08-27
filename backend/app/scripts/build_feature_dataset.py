"""Build a versioned model-feature dataset and JSON quality report from stored source data."""

import argparse
from datetime import datetime
from pathlib import Path

from app.db.database import get_session_factory
from app.services.feature_dataset_service import (
    FeatureDatasetError,
    FeatureDatasetNotReadyError,
    build_feature_dataset,
)


def parse_datetime(value: str) -> datetime:
    """Parse an ISO-8601 command-line timestamp, including a trailing Z."""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use ISO-8601, for example 2025-08-01T00:00:00Z.") from exc


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build Energy Grid model features from stored source data."
    )
    parser.add_argument("--start", required=True, type=parse_datetime)
    parser.add_argument("--end", required=True, type=parse_datetime)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    session_factory = get_session_factory()
    with session_factory() as session:
        try:
            result = build_feature_dataset(
                session,
                start=args.start,
                end=args.end,
                output_dir=args.output_dir,
            )
        except (FeatureDatasetError, FeatureDatasetNotReadyError) as exc:
            raise SystemExit(f"Feature dataset build failed: {exc}") from exc
    print(
        "Feature dataset finished: "
        f"version={result.dataset_version}, rows={result.row_count}, csv={result.csv_path}, "
        f"quality_report={result.quality_report_path}."
    )


if __name__ == "__main__":
    main()
