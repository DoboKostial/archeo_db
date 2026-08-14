import hashlib
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import jwt

from app import create_app
from config import Config


class _Cursor:
    def __init__(self, row):
        self.row = row
        self.params = None

    def execute(self, _query, params=None):
        self.params = params

    def fetchone(self):
        return self.row

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False


class _Connection:
    def __init__(self, row):
        self.cursor_instance = _Cursor(row)
        self.committed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True


class QrLoginTests(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
        self.client = app.test_client()

    @staticmethod
    def _connection_factory(connection):
        @contextmanager
        def factory():
            yield connection

        return factory

    def test_valid_grant_returns_standard_mobile_session(self):
        login_code = "A" * 43
        connection = _Connection(("user@example.test", "Test User", "archeolog", True))

        with patch(
            "app.routes.auth.auth_connection",
            self._connection_factory(connection),
        ):
            response = self.client.post(
                "/api/mobile/auth/qr-login",
                json={"code": login_code},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(connection.committed)
        self.assertEqual(
            connection.cursor_instance.params,
            (hashlib.sha256(login_code.encode("ascii")).hexdigest(),),
        )
        payload = response.get_json()
        claims = jwt.decode(
            payload["access_token"],
            Config.JWT_SECRET_KEY,
            algorithms=["HS256"],
        )
        self.assertEqual(claims["email"], "user@example.test")
        self.assertEqual(claims["client"], "mobile")
        self.assertEqual(claims["type"], "access")

    def test_expired_or_used_grant_is_rejected(self):
        connection = _Connection(None)

        with patch(
            "app.routes.auth.auth_connection",
            self._connection_factory(connection),
        ):
            response = self.client.post(
                "/api/mobile/auth/qr-login",
                json={"code": "B" * 43},
            )

        self.assertEqual(response.status_code, 401)
        self.assertTrue(connection.committed)

    def test_disabled_user_is_rejected(self):
        connection = _Connection(("disabled@example.test", "Disabled", "tester", False))

        with patch(
            "app.routes.auth.auth_connection",
            self._connection_factory(connection),
        ):
            response = self.client.post(
                "/api/mobile/auth/qr-login",
                json={"code": "C" * 43},
            )

        self.assertEqual(response.status_code, 403)

    def test_malformed_code_is_rejected_before_database_access(self):
        with patch("app.routes.auth.auth_connection") as auth_connection:
            response = self.client.post(
                "/api/mobile/auth/qr-login",
                json={"code": "too-short"},
            )

        self.assertEqual(response.status_code, 401)
        auth_connection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
