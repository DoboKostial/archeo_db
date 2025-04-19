#!/usr/bin/env python3
# this is emergency script if normal way of creatin users via web_app fails
# and You need to insert hash into table app_users
# usage: python3 create_user.py "Karel Novák" karel@example.com archeolog
# author: dobo@dobo.sk

import sys
import hashlib
import os
import binascii

def generate_password_hash(password: str, salt_len: int = 16, iterations: int = 260000) -> str:
    salt = os.urandom(salt_len)
    hash_bytes = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, iterations)
    salt_hex = binascii.hexlify(salt).decode()
    hash_hex = binascii.hexlify(hash_bytes).decode()
    return f"pbkdf2:sha256:{iterations}${salt_hex}${hash_hex}"

def generate_random_password(length: int = 12) -> str:
    import secrets
    import string
    characters = string.ascii_letters + string.digits
    return ''.join(secrets.choice(characters) for _ in range(length))

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("usage: python3 create_user.py \"Name Surname \" email@example.com group_role")
        sys.exit(1)

    name = sys.argv[1]
    mail = sys.argv[2]
    role = sys.argv[3]

    raw_password = generate_random_password()
    password_hash = generate_password_hash(raw_password)

    print("You can copy these strings directly to auth_db.app_users:\n")
    print(f"Name            : {name}")
    print(f"E-mail          : {mail}")
    print(f"Group Role      : {role}")
    print(f"Temp password   : {raw_password}")
    print(f"Password hash   : {password_hash}")
