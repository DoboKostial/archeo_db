import logging
import os

# Nastavení cesty pro logovací soubory
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../log')
os.makedirs(LOG_DIR, exist_ok=True)

# Konfigurace loggeru
def setup_logger(log_name):
    logger = logging.getLogger(log_name)
    logger.setLevel(logging.INFO)

    # Formát logů
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    # File handler
    file_handler = logging.FileHandler(os.path.join(LOG_DIR, f"{log_name}.log"))
    file_handler.setFormatter(formatter)

    # Stream handler (pro konzoli)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    return logger
