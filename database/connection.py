import os
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv


SCHEMA_FILE = Path(__file__).with_name("schema.sql")
load_dotenv(SCHEMA_FILE.parent.parent / ".env")


def connect_database() -> mysql.connector.MySQLConnection:
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DATABASE", "gympy"),
    )


def initialize_database(connection: mysql.connector.MySQLConnection) -> None:
    schema = SCHEMA_FILE.read_text(encoding="utf-8")
    cursor = connection.cursor()
    try:
        for statement in schema.split(";"):
            if statement.strip():
                cursor.execute(statement)
        cursor.execute("SHOW COLUMNS FROM clients LIKE 'contact'")
        if cursor.fetchone() is not None:
            cursor.execute("ALTER TABLE clients DROP COLUMN contact")
        cursor.execute("SHOW COLUMNS FROM clients LIKE 'archived_at'")
        if cursor.fetchone() is None:
            cursor.execute(
                "ALTER TABLE clients ADD COLUMN archived_at VARCHAR(40) NULL"
            )
        cursor.execute("SHOW COLUMNS FROM clients LIKE 'email'")
        if cursor.fetchone() is None:
            cursor.execute(
                "ALTER TABLE clients "
                "ADD COLUMN email VARCHAR(254) NOT NULL DEFAULT ''"
            )
        for column, definition in (
            ("is_pwd", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("is_student", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("is_worker", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("id_number", "VARCHAR(100) NOT NULL DEFAULT ''"),
        ):
            cursor.execute(f"SHOW COLUMNS FROM clients LIKE '{column}'")
            if cursor.fetchone() is None:
                cursor.execute(
                    f"ALTER TABLE clients ADD COLUMN {column} {definition}"
                )
    finally:
        cursor.close()
