import logging


def configure_logging(level: str) -> None:
    """Configure safe application logging without including environment values."""
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # httpx logs fully rendered request URLs at INFO. Provider credentials can be sent in a
    # query parameter, so keep transport logs out of normal application output.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
