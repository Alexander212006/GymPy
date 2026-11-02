import getpass
import hashlib
import hmac
import secrets

import mysql.connector


HASH_ALGORITHM = "pbkdf2_sha256"
HASH_ITERATIONS = 600_000
CREDENTIAL_ID = 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        HASH_ITERATIONS,
    )
    return (
        f"{HASH_ALGORITHM}${HASH_ITERATIONS}"
        f"${salt.hex()}${password_hash.hex()}"
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt_hex, expected_hash_hex = stored_hash.split("$")
        iterations = int(iterations_text)
        salt = bytes.fromhex(salt_hex)
        expected_hash = bytes.fromhex(expected_hash_hex)
    except (ValueError, TypeError) as error:
        raise ValueError("The stored password hash is invalid.") from error

    if algorithm != HASH_ALGORITHM or iterations <= 0 or not salt or not expected_hash:
        raise ValueError("The stored password hash is invalid.")

    actual_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual_hash, expected_hash)


def initialize_password(
    connection: mysql.connector.MySQLConnection,
) -> tuple[str, bool]:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT password_hash FROM app_credentials WHERE id = %s",
            (CREDENTIAL_ID,),
        )
        result = cursor.fetchone()
        if result is not None:
            return result[0], False

        print("First-time setup: create your GymPy login password.")
        while True:
            password = getpass.getpass("New password: ")
            if not password:
                print("Password cannot be empty.")
                continue
            confirmation = getpass.getpass("Confirm password: ")
            if password == confirmation:
                break
            print("Passwords do not match. Please try again.\n")

        password_hash = hash_password(password)
        cursor.execute(
            "INSERT INTO app_credentials (id, password_hash) VALUES (%s, %s)",
            (CREDENTIAL_ID, password_hash),
        )
        connection.commit()
        return password_hash, True
    except mysql.connector.Error:
        connection.rollback()
        raise
    finally:
        cursor.close()
