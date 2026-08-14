import hashlib
import hmac
import unittest
from contextlib import contextmanager
from urllib.parse import parse_qs, urlsplit
from unittest.mock import MagicMock, patch

import jwt

from config import Config
from app import create_app
from app.routes.auth import _send_password_reset_email


class PasswordResetMailTests(unittest.TestCase):
    def test_starttls_relay_uses_configured_credentials_and_sender(self):
        settings = {
            "ADMIN_NAME": "Admin",
            "ADMIN_EMAIL": "admin@example.test",
            "MAIL_SERVER": "smtp.example.test",
            "MAIL_PORT": 587,
            "MAIL_USERNAME": "noreply@example.test",
            "MAIL_PASSWORD": "secret",
            "MAIL_USE_TLS": True,
            "MAIL_USE_SSL": False,
            "MAIL_TIMEOUT": 12,
            "MAIL_DEFAULT_SENDER": "ArcheoDB <noreply@example.test>",
            "MAIL_REPLY_TO": "admin@example.test",
        }

        with patch.multiple(Config, create=True, **settings), patch(
            "app.routes.auth.smtplib.SMTP",
        ) as smtp_class:
            smtp = smtp_class.return_value.__enter__.return_value
            _send_password_reset_email(
                "user@example.test",
                "Test User",
                "https://example.test/forgot-password?token=test",
            )

        smtp_class.assert_called_once_with("smtp.example.test", 587, timeout=12)
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with("noreply@example.test", "secret")
        message = smtp.send_message.call_args.args[0]
        self.assertEqual(message["From"], "ArcheoDB <noreply@example.test>")
        self.assertEqual(message["Reply-To"], "admin@example.test")
        self.assertEqual(message["To"], "user@example.test")

    def test_forgot_password_token_is_accepted_by_web_token_contract(self):
        password_hash = "scrypt:32768:8:1$test$hash"
        web_secret = "web-secret-for-test"
        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (
            "user@example.test",
            "Test User",
            password_hash,
            True,
        )

        @contextmanager
        def connection_factory():
            yield conn

        app = create_app()
        app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
        with patch.object(Config, "WEB_BASE_URL", "https://example.test"), patch.object(
            Config,
            "WEB_PASSWORD_RESET_SECRET_KEY",
            web_secret,
        ), patch(
            "app.routes.auth.auth_connection",
            connection_factory,
        ), patch(
            "app.routes.auth._send_password_reset_email",
        ) as send_mail:
            response = app.test_client().post(
                "/api/mobile/auth/forgot-password",
                json={"email": "user@example.test"},
            )

        self.assertEqual(response.status_code, 200)
        reset_url = send_mail.call_args.args[2]
        token = parse_qs(urlsplit(reset_url).query)["token"][0]
        signing_key = hmac.new(
            web_secret.encode("utf-8"),
            b"password-reset-token",
            hashlib.sha256,
        ).digest()
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["HS256"],
            audience="archeodb-password-reset",
            issuer="archeodb-web",
        )
        binding_key = hmac.new(
            web_secret.encode("utf-8"),
            b"password-reset-binding",
            hashlib.sha256,
        ).digest()
        expected_fingerprint = hmac.new(
            binding_key,
            password_hash.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(payload["type"], "password_reset")
        self.assertEqual(payload["sub"], "user@example.test")
        self.assertEqual(payload["password_fingerprint"], expected_fingerprint)


if __name__ == "__main__":
    unittest.main()
