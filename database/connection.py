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
        cursor.execute("SHOW COLUMNS FROM payments LIKE 'assisting_employee'")
        if cursor.fetchone() is None:
            cursor.execute(
                "ALTER TABLE payments ADD COLUMN assisting_employee "
                "VARCHAR(255) NOT NULL DEFAULT ''"
            )
        cursor.execute("SHOW COLUMNS FROM maintenance LIKE 'performed_by'")
        if cursor.fetchone() is None:
            cursor.execute(
                "ALTER TABLE maintenance ADD COLUMN performed_by "
                "VARCHAR(255) NOT NULL DEFAULT ''"
            )
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
        ):
            cursor.execute(f"SHOW COLUMNS FROM clients LIKE '{column}'")
            if cursor.fetchone() is None:
                cursor.execute(
                    f"ALTER TABLE clients ADD COLUMN {column} {definition}"
                )
        cursor.execute("SHOW COLUMNS FROM clients LIKE 'id_number'")
        has_id_number = cursor.fetchone() is not None
        cursor.execute("SHOW COLUMNS FROM clients LIKE 'valid_id_number'")
        has_valid_id_number = cursor.fetchone() is not None
        if has_id_number and has_valid_id_number:
            cursor.execute(
                "UPDATE clients SET valid_id_number = id_number "
                "WHERE valid_id_number = '' AND id_number <> ''"
            )
            cursor.execute("ALTER TABLE clients DROP COLUMN id_number")
        elif has_id_number:
            cursor.execute(
                "ALTER TABLE clients CHANGE COLUMN id_number valid_id_number "
                "VARCHAR(100) NOT NULL DEFAULT ''"
            )
        elif not has_valid_id_number:
            cursor.execute(
                "ALTER TABLE clients ADD COLUMN valid_id_number "
                "VARCHAR(100) NOT NULL DEFAULT ''"
            )
        cursor.execute("SHOW COLUMNS FROM clients LIKE 'membership'")
        has_membership = cursor.fetchone() is not None
        cursor.execute("SHOW COLUMNS FROM clients LIKE 'is_member'")
        has_is_member = cursor.fetchone() is not None
        if not has_is_member:
            cursor.execute(
                "ALTER TABLE clients ADD COLUMN is_member "
                "BOOLEAN NOT NULL DEFAULT FALSE"
            )
        if has_membership:
            cursor.execute(
                "ALTER TABLE clients DROP COLUMN membership"
            )
        cursor.execute("SHOW COLUMNS FROM clients LIKE 'welcome_email_status'")
        welcome_email_status_column = cursor.fetchone()
        if welcome_email_status_column is None:
            # Existing clients predate automatic welcome emails. Mark them as
            # ineligible so a future code path cannot email them by accident.
            cursor.execute(
                "ALTER TABLE clients ADD COLUMN welcome_email_status "
                "VARCHAR(20) NOT NULL DEFAULT 'not_applicable'"
            )
            cursor.execute(
                "ALTER TABLE clients MODIFY COLUMN welcome_email_status "
                "VARCHAR(20) NOT NULL DEFAULT 'pending'"
            )
        elif welcome_email_status_column[4] != "pending":
            cursor.execute(
                "ALTER TABLE clients MODIFY COLUMN welcome_email_status "
                "VARCHAR(20) NOT NULL DEFAULT 'pending'"
            )
        for column, definition in (
            ("welcome_email_attempted_at", "VARCHAR(40) NULL"),
            ("welcome_email_sent_at", "VARCHAR(40) NULL"),
            ("welcome_email_message_id", "VARCHAR(255) NULL"),
        ):
            cursor.execute(f"SHOW COLUMNS FROM clients LIKE '{column}'")
            if cursor.fetchone() is None:
                cursor.execute(
                    f"ALTER TABLE clients ADD COLUMN {column} {definition}"
                )
        cursor.execute(
            "UPDATE clients SET is_member = EXISTS ("
            "SELECT 1 FROM payments "
            "WHERE payments.client_id = clients.client_id "
            "AND LOWER(payments.description) = 'gym membership')"
        )
        connection.commit()
    except mysql.connector.Error:
        connection.rollback()
        raise
    finally:
        cursor.close()
