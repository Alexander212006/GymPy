import getpass
from datetime import datetime
from decimal import Decimal, InvalidOperation

import mysql.connector

from database.authentication import initialize_password, verify_password
from database.connection import connect_database, initialize_database


MAX_ATTEMPTS = 3
MENU_OPTIONS = (
    "Client records",
    "Add client profile",
    "Log client attendance",
    "Client payment",
    "Payment history",
    "Machine maintenance record",
)
def insert_record(
    cursor: mysql.connector.cursor.MySQLCursor,
    collection: str,
    record: dict[str, str],
) -> None:
    if collection == "clients":
        statement = (
            "INSERT INTO clients "
            "(client_id, name, contact, membership, created_at) "
            "VALUES (%s, %s, %s, %s, %s)"
        )
        values = (
            record["client_id"],
            record["name"],
            record["contact"],
            record["membership"],
            record["created_at"],
        )
    elif collection == "attendance":
        statement = (
            "INSERT INTO attendance (client_id, client_name, timestamp) "
            "VALUES (%s, %s, %s)"
        )
        values = (record["client_id"], record["client_name"], record["timestamp"])
    elif collection == "payments":
        statement = (
            "INSERT INTO payments "
            "(client_id, client_name, amount, description, timestamp) "
            "VALUES (%s, %s, %s, %s, %s)"
        )
        values = (
            record["client_id"],
            record["client_name"],
            record["amount"],
            record["description"],
            record["timestamp"],
        )
    elif collection == "maintenance":
        statement = (
            "INSERT INTO maintenance (machine, description, cost, timestamp) "
            "VALUES (%s, %s, %s, %s)"
        )
        values = (
            record["machine"],
            record["description"],
            record["cost"],
            record["timestamp"],
        )
    else:
        raise ValueError(f"Unknown data collection: {collection}")
    cursor.execute(statement, values)


def load_data(
    connection: mysql.connector.MySQLConnection,
) -> dict[str, list[dict[str, str]]]:
    queries = {
        "clients": (
            "SELECT client_id, name, contact, membership, created_at "
            "FROM clients ORDER BY id"
        ),
        "attendance": (
            "SELECT client_id, client_name, timestamp "
            "FROM attendance ORDER BY id"
        ),
        "payments": (
            "SELECT client_id, client_name, amount, description, timestamp "
            "FROM payments ORDER BY id"
        ),
        "maintenance": (
            "SELECT machine, description, cost, timestamp "
            "FROM maintenance ORDER BY id"
        ),
    }
    data: dict[str, list[dict[str, str]]] = {}
    cursor = connection.cursor(dictionary=True)
    try:
        for collection, query in queries.items():
            cursor.execute(query)
            records = cursor.fetchall()
            data[collection] = [
                {
                    key: format(value, ".2f")
                    if isinstance(value, Decimal)
                    else str(value)
                    for key, value in record.items()
                }
                for record in records
            ]
    finally:
        cursor.close()
    return data


def save_record(
    connection: mysql.connector.MySQLConnection,
    data: dict[str, list[dict[str, str]]],
    collection: str,
    record: dict[str, str],
) -> None:
    cursor = connection.cursor()
    try:
        insert_record(cursor, collection, record)
        connection.commit()
    except mysql.connector.Error:
        connection.rollback()
        raise
    finally:
        cursor.close()
    data[collection].append(record)


def current_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def prompt_required(label: str) -> str:
    while True:
        value = input(label).strip()
        if value:
            return value
        print("This field is required.")


def prompt_amount(label: str, *, allow_zero: bool = False) -> str:
    while True:
        entered_amount = input(label).strip()
        try:
            amount = Decimal(entered_amount)
        except InvalidOperation:
            print("Enter a valid amount using digits and an optional decimal point.")
            continue

        if not amount.is_finite() or amount < 0 or (amount == 0 and not allow_zero):
            qualifier = "zero or greater" if allow_zero else "greater than zero"
            print(f"Amount must be {qualifier}.")
            continue
        return f"{amount:.2f}"


def next_client_id(clients: list[dict[str, str]]) -> str:
    largest_id = max(
        (
            int(client["client_id"][1:])
            for client in clients
            if client.get("client_id", "").startswith("C")
                and client["client_id"][1:].isdigit()
        ),
        default=0,
    )
    return f"C{largest_id + 1:04d}"


def select_client(data: dict[str, list[dict[str, str]]]) -> dict[str, str] | None:
    clients = data["clients"]
    if not clients:
        print("There are no client profiles yet. Add a client profile first.")
        return None

    print("\nRegistered clients:")
    for client in clients:
        print(f"  {client['client_id']} - {client['name']}")

    client_id = prompt_required("Enter client ID: ").upper()
    for client in clients:
        if client["client_id"].upper() == client_id:
            return client
    print("No client found with that ID.")
    return None


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


def show_clients(data: dict[str, list[dict[str, str]]]) -> None:
    clients = data["clients"]
    print("\nCLIENT RECORDS")
    if not clients:
        print("No client profiles found.")
        return

    for client in clients:
        print(
            f"{client['client_id']} | {client['name']} | "
            f"Contact: {client['contact']} | Plan: {client['membership']}"
        )


def add_client(
    data: dict[str, list[dict[str, str]]],
    connection: mysql.connector.MySQLConnection,
) -> None:
    print("\nADD CLIENT PROFILE")
    record = {
        "client_id": next_client_id(data["clients"]),
        "name": prompt_required("Full name: "),
        "contact": prompt_required("Contact number: "),
        "membership": prompt_required("Membership plan: "),
        "created_at": current_timestamp(),
    }
    save_record(connection, data, "clients", record)
    print(f"Client profile saved. Client ID: {record['client_id']}")


def log_attendance(
    data: dict[str, list[dict[str, str]]],
    connection: mysql.connector.MySQLConnection,
) -> None:
    print("\nLOG CLIENT ATTENDANCE")
    client = select_client(data)
    if client is None:
        return

    record = {
        "client_id": client["client_id"],
        "client_name": client["name"],
        "timestamp": current_timestamp(),
    }
    save_record(connection, data, "attendance", record)
    print(f"Attendance logged for {client['name']}.")


def record_payment(
    data: dict[str, list[dict[str, str]]],
    connection: mysql.connector.MySQLConnection,
) -> None:
    print("\nCLIENT PAYMENT")
    client = select_client(data)
    if client is None:
        return

    record = {
        "client_id": client["client_id"],
        "client_name": client["name"],
        "amount": prompt_amount("Payment amount: "),
        "description": prompt_required("Payment description: "),
        "timestamp": current_timestamp(),
    }
    save_record(connection, data, "payments", record)
    print(f"Payment of {record['amount']} recorded for {client['name']}.")


def show_payment_history(data: dict[str, list[dict[str, str]]]) -> None:
    payments = data["payments"]
    print("\nPAYMENT HISTORY")
    if not payments:
        print("No payments recorded.")
        return

    for payment in payments:
        print(
            f"{payment['timestamp']} | {payment['client_id']} - "
            f"{payment['client_name']} | {payment['amount']} | "
            f"{payment['description']}"
        )


def record_maintenance(
    data: dict[str, list[dict[str, str]]],
    connection: mysql.connector.MySQLConnection,
) -> None:
    print("\nMACHINE MAINTENANCE RECORD")
    record = {
        "machine": prompt_required("Machine or equipment name: "),
        "description": prompt_required("Maintenance performed: "),
        "cost": prompt_amount("Maintenance cost (enter 0 if none): ", allow_zero=True),
        "timestamp": current_timestamp(),
    }
    save_record(connection, data, "maintenance", record)
    print(f"Maintenance record saved for {record['machine']}.")


def show_menu(
    data: dict[str, list[dict[str, str]]],
    connection: mysql.connector.MySQLConnection,
) -> None:
    actions = (
        show_clients,
        lambda records: add_client(records, connection),
        lambda records: log_attendance(records, connection),
        lambda records: record_payment(records, connection),
        show_payment_history,
        lambda records: record_maintenance(records, connection),
    )
    while True:
        print("\n" + "=" * 42)
        print("              GYMPY MAIN MENU")
        print("=" * 42)
        for number, option in enumerate(MENU_OPTIONS, start=1):
            print(f"  {number}. {option}")
        print("  7. Logout")

        choice = input("\nChoose an option: ").strip()
        if choice == "7":
            print("Logged out. Goodbye!")
            return

        if not choice.isdigit() or not 1 <= int(choice) <= len(actions):
            print("Invalid option. Please choose a number from 1 to 7.")
            continue

        try:
            actions[int(choice) - 1](data)
        except mysql.connector.Error as error:
            print(f"Could not save the record to MySQL: {error}")


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
