#!/usr/bin/env python3
# this is emergency script if normal way of creatin users via web_app fails
# and You need to insert hash into table app_users
# prerequisities in your python (except standard library): werkzeug
# usage: python3 create_user.py "Karel Novák" karel@example.com archeolog
# author: dobo@dobo.sk

import sys
import secrets
import string
from werkzeug.security import generate_password_hash

def generate_random_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def generate_scrypt_hash(password: str) -> str:
    return generate_password_hash(password, method='scrypt')

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python3 create_user_emergency.py \"Name Surname\" email@example.com group_role")
        sys.exit(1)

    name = sys.argv[1]
    mail = sys.argv[2]
    role = sys.argv[3]

    raw_password = generate_random_password()
    password_hash = generate_scrypt_hash(raw_password)

    print("\nCopy these values into auth_db.app_users:\n")
    print(f"Name              : {name}")
    print(f"E-mail            : {mail}")
    print(f"Group_role        : {role}")
    print(f"Temporary password: {raw_password}")
    print(f"Password hash     : {password_hash}")
