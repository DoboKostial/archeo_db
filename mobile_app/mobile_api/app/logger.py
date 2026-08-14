import logging

from config import Config


def setup_logger() -> logging.Logger:
    logger = logging.getLogger("mobile_api")
    if logger.handlers:
        return logger

    level_name = getattr(Config, "LOG_LEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, level_name, logging.INFO))

    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        )
    )
    logger.addHandler(handler)
    logger.propagate = False
    return logger

