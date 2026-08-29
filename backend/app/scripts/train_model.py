"""Train and activate the Phase 8 baseline demand model from a Phase 7 CSV."""

import argparse
from pathlib import Path

from app.db.database import get_session_factory
from app.services.forecast_model_service import ModelTrainingError, train_baseline_model


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train the city-level baseline demand model from a Phase 7 feature CSV."
    )
    parser.add_argument("--dataset", type=Path, required=True)
    args = parser.parse_args()

    session_factory = get_session_factory()
    with session_factory() as session:
        try:
            result = train_baseline_model(session, dataset_path=args.dataset)
        except ModelTrainingError as exc:
            raise SystemExit(f"Model training failed: {exc}") from exc
    print(
        "Baseline model ready: "
        f"version={result.version}, training_rows={result.training_row_count}, "
        f"validation_rows={result.validation_row_count}, mae_mw={result.mae_mw}, "
        f"rmse_mw={result.rmse_mw}, mape_percent={result.mape_percent}, "
        f"artifact={result.artifact_path}, validation_export={result.validation_predictions_path}."
    )


if __name__ == "__main__":
    main()
