# app/utils/auth.py
# helpers for auth

import smtplib
from email.message import EmailMessage
from functools import wraps
from psycopg2 import sql
import secrets, string, jwt
from flask import session, redirect, url_for, request
from config import Config
from app.logger import logger
from app.database import get_auth_connection
from app.queries import get_user_role
from app.utils.admin import _get_base_url


def generate_random_password(length: int = 12) -> str:
    # we wont log password only its length
    logger.info(f"Generating random password (length={length})")
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))


def send_new_account_email(user_email: str, user_name: str, password: str) -> None:
    logger.info(f"Preparing new-account email for {user_email}")
    base_url = _get_base_url()
    msg = EmailMessage()
    msg['Subject'] = 'Your account in ArcheoDB test environment was created'
    msg['From'] = Config.ADMIN_EMAIL
    msg['To'] = user_email
    msg.set_content(
        f"Hi {user_name},\n\n"
        f"an access to ArcheoDB ({base_url}) was granted.\n\n"
        f"Your credentials:\n"
        f"E-mail: {user_email}\n"
        f"Password: {password}\n\n"
        f"You are encouraged to change Your password immediately after first succesfull login (in Profile section).\n\n"
        f"Have a nice day,\n{Config.ADMIN_NAME}"
    )
    try:
        with smtplib.SMTP('localhost') as smtp:
            smtp.send_message(msg)
        logger.info(f"New-account email was sent to {user_email}")
    except Exception as e:
        logger.error(f"While sending an email to new user {user_email} an error occured: {e}")


def send_password_reset_email(user_email: str, user_name: str, reset_url: str) -> None:
    logger.info(f"Preparing password-reset email for {user_email}")
    msg = EmailMessage()
    msg['Subject'] = 'Password reset for ArcheoDB'
    msg['From'] = Config.ADMIN_EMAIL
    msg['To'] = user_email
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

    try:
        with smtplib.SMTP('localhost') as smtp:
            smtp.send_message(msg)
        logger.info(f"Password-reset email was sent to {user_email}")
    except Exception as e:
        logger.error(f"Error while sending password-reset email to {user_email}: {e}")


def generate_random_password(length: int = 12) -> str:
    # we wont log password only its length
    logger.info(f"Generating random password (length={length})")
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))



def send_password_change_email(user_email: str, user_name: str) -> None:
    logger.info(f"Preparing password-change email for {user_email}")
    msg = EmailMessage()
    msg['Subject'] = 'Password Changed Notification'
    msg['From'] = Config.ADMIN_EMAIL
    msg['To'] = user_email
    msg.set_content(
        f"Dear {user_name},\n\nYour password in ArcheoDB has been changed.\n"
        f"If you are not aware of this action, please contact the application administrator: "
        f"{Config.ADMIN_NAME} ({Config.ADMIN_EMAIL})."
    )

    try:
        with smtplib.SMTP('localhost') as smtp:
            smtp.send_message(msg)
        logger.info(f"Password-change email was sent to {user_email}")
    except Exception as e:
        logger.error(f"Error while sending password-change email to {user_email}: {e}")



def archeolog_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.cookies.get('token')
        if not token:
            logger.warning("Admin access without token -> /login")
            return redirect('/login')

        try:
            payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
            email = payload.get('email')
        except jwt.ExpiredSignatureError:
            logger.warning("Expired token on admin access -> /login")
            return redirect('/login')
        except jwt.InvalidTokenError:
            logger.warning("Invalid token on admin access -> /login")
            return redirect('/login')

        # check role directly from DB
        role = None
        try:
            with get_auth_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(get_user_role(), (email,))
                    role = cur.fetchone()[0] if cur.rowcount else None
        except Exception as e:
            logger.error(f"Role check failed for {email}: {e}")
            return redirect(url_for('main.index'))

        if role != 'archeolog':
            logger.warning(f"User {email} (role={role}) blocked from admin")
            return redirect(url_for('main.index'))

        # renewing session for further use (eg. flashy/UI)
        session['user_email'] = email
        session['user_role'] = role
        return f(*args, **kwargs)
    return decorated_function