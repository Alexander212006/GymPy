import getpass

import mysql.connector

from database.authentication import initialize_password, verify_password

from .common import MAX_ATTEMPTS

def show_welcome() -> None:
    print("=" * 42)
    print("          G Y M P Y   M A N A G E R")
    print("              Your gym, organized.")
    print("=" * 42)
    print("                 LOGIN")
    print()

def login(connection: mysql.connector.MySQLConnection) -> bool:
    password_hash, initialized = initialize_password(connection)
    if initialized:
        print("\nPassword saved. Welcome to GymPy!")
        return True

    for attempt in range(MAX_ATTEMPTS):
        entered_password = getpass.getpass("Enter password: ")
        if verify_password(entered_password, password_hash):
            print("\nAccess granted. Welcome to GymPy!")
            return True

        attempts_left = MAX_ATTEMPTS - attempt - 1
        if attempts_left:
            print(f"Incorrect password. {attempts_left} attempt(s) remaining.\n")

    print("\nToo many incorrect attempts. Access denied.")
    return False
