import os
import logging
from flask import Flask

def setup_logging():
    log_dir = os.path.join(os.path.dirname(__file__), '..', 'log')
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, 'app_archeodb.log')

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )

def create_app():
    setup_logging()

    app = Flask(__name__)  # Flask  searching for templates in app/templates`
    
    from app.routes import main
    app.register_blueprint(main)

    return app
