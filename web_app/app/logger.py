import logging
import os
from config import Config

def setup_logger(log_name="archeodb"):
    log_path = Config.APP_LOG
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    logger = logging.getLogger(log_name)
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    # Avoiding handler duplication if multiple imports
    if not logger.handlers:
        file_handler = logging.FileHandler(log_path)
        file_handler.setFormatter(formatter)
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.addHandler(stream_handler)

    return logger

