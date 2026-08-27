import logging


def configure_logging(level: str) -> None:
    """Configure safe application logging without including environment values."""
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

