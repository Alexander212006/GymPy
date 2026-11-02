import os
from pathlib import Path

import mysql.connector


SCHEMA_FILE = Path(__file__).with_name("schema.sql")


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
    finally:
        cursor.close()
