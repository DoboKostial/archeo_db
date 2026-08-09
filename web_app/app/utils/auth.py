# app/utils/auth.py
# helpers for auth

import smtplib
import ssl
from email.message import EmailMessage
import secrets, string
from config import Config
from app.logger import logger
from app.utils.admin import _get_base_url


def generate_random_password(length: int = 12) -> str:
    if length < 12:
        raise ValueError("Generated passwords must be at least 12 characters long.")
    logger.info(f"Generating random password (length={length})")
    chars = string.ascii_letters + string.digits + "!@#$%"
    password = [
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%"),
    ]
    password.extend(secrets.choice(chars) for _ in range(length - len(password)))
    secrets.SystemRandom().shuffle(password)
    return ''.join(password)


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _mail_sender() -> str:
    return (getattr(Config, "MAIL_DEFAULT_SENDER", "") or Config.ADMIN_EMAIL).strip()


def _mail_reply_to() -> str:
    return (getattr(Config, "MAIL_REPLY_TO", "") or Config.ADMIN_EMAIL).strip()


def _message(subject: str, to_email: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = _mail_sender()
    msg["To"] = to_email
    reply_to = _mail_reply_to()
    if reply_to:
        msg["Reply-To"] = reply_to
    return msg


def _login_if_configured(smtp) -> None:
    username = (getattr(Config, "MAIL_USERNAME", "") or "").strip()
    password = getattr(Config, "MAIL_PASSWORD", "") or ""
    if username:
        smtp.login(username, password)


def _send_email(msg: EmailMessage, success_message: str, error_context: str) -> None:
    server = (getattr(Config, "MAIL_SERVER", "localhost") or "").strip()
    port = int(getattr(Config, "MAIL_PORT", 25) or 25)
    timeout = int(getattr(Config, "MAIL_TIMEOUT", 10) or 10)
    use_tls = _as_bool(getattr(Config, "MAIL_USE_TLS", False))
    use_ssl = _as_bool(getattr(Config, "MAIL_USE_SSL", False))

    if not server:
        logger.error("MAIL_SERVER is not configured.")
        return
    if use_tls and use_ssl:
        logger.error("MAIL_USE_TLS and MAIL_USE_SSL cannot both be enabled.")
        return

    try:
        context = ssl.create_default_context()
        if use_ssl:
            with smtplib.SMTP_SSL(server, port, timeout=timeout, context=context) as smtp:
                _login_if_configured(smtp)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(server, port, timeout=timeout) as smtp:
                if use_tls:
                    smtp.starttls(context=context)
                _login_if_configured(smtp)
                smtp.send_message(msg)
        logger.info(success_message)
    except Exception as e:
        logger.error(f"{error_context}: {e}")


def send_new_account_email(user_email: str, user_name: str, password: str) -> None:
    logger.info(f"Preparing new-account email for {user_email}")
    base_url = _get_base_url()
    msg = _message('Your account in ArcheoDB was created', user_email)
    msg.set_content(
        f"Hi {user_name},\n\n"
        f"an access to ArcheoDB ({base_url}) was granted.\n\n"
        f"Your credentials:\n"
        f"E-mail: {user_email}\n"
        f"Password: {password}\n\n"
        f"You are encouraged to change Your password immediately after first succesfull login (in Profile section).\n\n"
        f"Have a nice day,\n{Config.ADMIN_NAME}"
    )
    _send_email(
        msg,
        f"New-account email was sent to {user_email}",
        f"While sending an email to new user {user_email} an error occurred",
    )


def send_password_reset_email(user_email: str, user_name: str, reset_url: str) -> None:
    logger.info(f"Preparing password-reset email for {user_email}")
    msg = _message('Password reset for ArcheoDB', user_email)
    msg.set_content(
        f"Hi {user_name},\n\n"
        f"You requested for password reset ArcheoDB system.\n"
        f"For new password please use the following link:\n\n"
        f"{reset_url}\n\n"
        f"After this You will be requested to change Your password. This link is valid for 30 minutes.\n\n"
        f"If You DID NOT request for new password, please contact app admin immediately: "
        f"{Config.ADMIN_NAME} ({Config.ADMIN_EMAIL})\n\n"
        f"Have a nice day,\nArcheoDB team"
    )

    _send_email(
        msg,
        f"Password-reset email was sent to {user_email}",
        f"Error while sending password-reset email to {user_email}",
    )


def send_password_change_email(user_email: str, user_name: str) -> None:
    logger.info(f"Preparing password-change email for {user_email}")
    msg = _message('Password Changed Notification', user_email)
    msg.set_content(
        f"Dear {user_name},\n\nYour password in ArcheoDB has been changed.\n"
        f"If you are not aware of this action, please contact the application administrator: "
        f"{Config.ADMIN_NAME} ({Config.ADMIN_EMAIL})."
    )

    _send_email(
        msg,
        f"Password-change email was sent to {user_email}",
        f"Error while sending password-change email to {user_email}",
    )
