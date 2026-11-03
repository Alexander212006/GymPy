import sys
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.connection import connect_database, initialize_database
from database.queries import load_data
from app.auth import login, show_welcome
from app.menus import show_menu


def main() -> None:
    show_welcome()
    connection = None
    try:
        connection = connect_database()
        initialize_database(connection)
        if login(connection):
            data = load_data(connection)
            show_menu(data, connection)
    except (mysql.connector.Error, OSError, ValueError) as error:
        print(f"Could not start GymPy: {error}")
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    main()
