#!/usr/bin/env python3
# this is emergency script if normal way of creatin users via web_app fails
# and You need to insert hash into table app_users
# prerequisities in your python (except standard library): werkzeug
# usage: python3 create_user.py "Karel Novák" karel@example.com archeolog
# author: dobo@dobo.sk

import argparse
import secrets
import string
from werkzeug.security import generate_password_hash

def generate_random_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def generate_scrypt_hash(password: str) -> str:
    return generate_password_hash(password, method='scrypt')


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def insert_sql(name: str, mail: str, role: str, password_hash: str) -> str:
    return (
        "INSERT INTO public.app_users (mail, name, password_hash, group_role, enabled)\n"
        f"VALUES ({sql_literal(mail)}, {sql_literal(name)}, {sql_literal(password_hash)}, "
        f"{sql_literal(role)}, true)\n"
        "ON CONFLICT (mail) DO NOTHING;"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate an emergency ArcheoDB user password hash."
    )
    parser.add_argument("name")
    parser.add_argument("mail")
    parser.add_argument("role")
    parser.add_argument(
        "--password",
        help="Use a provided temporary password instead of generating one.",
    )
    parser.add_argument(
        "--sql-only",
        action="store_true",
        help="Print only an INSERT statement for auth_db.public.app_users.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    name = args.name
    mail = args.mail
    role = args.role

    raw_password = args.password or generate_random_password()
    password_hash = generate_scrypt_hash(raw_password)

    if args.sql_only:
        print(insert_sql(name, mail, role, password_hash))
        raise SystemExit(0)

    print("\nCopy these values into auth_db.app_users:\n")
    print(f"Name              : {name}")
    print(f"E-mail            : {mail}")
    print(f"Group_role        : {role}")
    print(f"Temporary password: {raw_password}")
    print(f"Password hash     : {password_hash}")
