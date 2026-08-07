import pytest

import app as app_package
from app import create_app
from app.utils.tokens import create_session_token


class _AuthConnection:
    def close(self):
        return None


@pytest.fixture
def app():
    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return flask_app


@pytest.fixture
def client(app, monkeypatch):
    monkeypatch.setattr(app_package, "get_auth_connection", lambda: _AuthConnection())
    monkeypatch.setattr(
        app_package,
        "get_user_access_state",
        lambda _conn, _email: ("Security Test", "tester", True),
    )
    client = app.test_client()
    token = create_session_token(
        "security-test@example.invalid",
        "Security Test",
        "tester",
        lifetime_minutes=5,
    )
    client.set_cookie("token", token)
    return client
