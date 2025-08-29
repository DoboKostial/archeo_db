# web_app/app/logger.py
import logging
import os
from config import Config

# one common logger for whole app
logger = logging.getLogger("archeodb")

if not logger.handlers:
    # loglevel could be customized in Config.LOG_LEVEL = "DEBUG" | "INFO" | "WARNING" | "ERROR"
    level_name = getattr(Config, "LOG_LEVEL", "INFO")
    level = getattr(logging, level_name.upper(), logging.INFO)
    logger.setLevel(level)

    # target file in Config.APP_LOG
    log_path = Config.APP_LOG
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # no double logging via root logger
    logger.propagate = False
