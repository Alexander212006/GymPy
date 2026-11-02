import getpass
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import mysql.connector

from database.authentication import initialize_password, verify_password
from database.connection import connect_database, initialize_database
from database.queries import (
    archive_client,
    has_attendance_on_date,
    load_archived_clients,
    load_data,
    restore_client,
    save_record,
    update_client,
)


MAX_ATTEMPTS = 3
MENU_OPTIONS = (
    "Client records",
    "Add client profile",
    "Attendance records",
    "Log client attendance",
    "Client payment",
    "Payment history",
    "Machine maintenance record",
)
EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def current_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def format_created_at(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%B %d, %Y")
    except ValueError:
        return f"Invalid date: {value}"


def format_attendance_datetime(value: str) -> tuple[str, str]:
    try:
        timestamp = datetime.fromisoformat(value)
        return timestamp.strftime("%B %d, %Y"), timestamp.strftime("%I:%M %p")
    except ValueError:
        return f"Invalid date/time: {value}", ""


def prompt_required(label: str) -> str:
    while True:
        value = input(label).strip()
        if value:
            return value
        print("This field is required.")


def prompt_phone(
    label: str = "Contact number: ",
    *,
    current: str | None = None,
) -> str:
    while True:
        suffix = input(f"{label}09").strip()
        if current is not None and not suffix:
            return current
        if len(suffix) == 9 and suffix.isascii() and suffix.isdigit():
            return f"09{suffix}"
        print("Enter exactly 9 digits after the 09 prefix.")


def prompt_email(label: str = "Email address: ") -> str:
    while True:
        email = input(label).strip()
        if EMAIL_PATTERN.fullmatch(email):
            return email
        print("Enter a valid email address.")


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
    clients = [
        client for client in data["clients"] if not client.get("archived_at")
    ]
    if not clients:
        print("There are no active client profiles. Add a client profile first.")
        return None

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
    clients = [
        client for client in data["clients"] if not client.get("archived_at")
    ]
    print("\nCLIENT RECORDS")
    if not clients:
        print("No active client profiles found.")
        return

    columns = ("Client ID", "Name", "Contact", "Email", "Membership", "Created At")
    rows = [
        (
            client["client_id"],
            client["name"],
            client["contact"],
            client["email"],
            client["membership"],
            format_created_at(client["created_at"]),
        )
        for client in clients
    ]
    widths = [
        max(len(columns[index]), *(len(row[index]) for row in rows))
        for index in range(len(columns))
    ]

    def format_row(values: tuple[str, ...]) -> str:
        return "| " + " | ".join(
            value.ljust(widths[index]) for index, value in enumerate(values)
        ) + " |"

    separator = "+-" + "-+-".join("-" * width for width in widths) + "-+"
    print(separator)
    print(format_row(columns))
    print(separator)
    for client in clients:
        print(
            format_row(
                (
                    client["client_id"],
                    client["name"],
                    client["contact"],
                    client["email"],
                    client["membership"],
                    format_created_at(client["created_at"]),
                )
            )
        )
    print(separator)


def add_client(
    data: dict[str, list[dict[str, str]]],
    connection: mysql.connector.MySQLConnection,
) -> None:
    show_clients(data)

    print("\nADD CLIENT PROFILE")
    name = prompt_required("Full name: ")
    contact = prompt_phone()
    email = prompt_email()

    normalized_name = " ".join(name.casefold().split())
    normalized_email = email.casefold()
    duplicate = next(
        (
            client
            for client in data["clients"]
            if not client.get("archived_at")
            and (
                (
                    " ".join(client["name"].casefold().split()) == normalized_name
                    and client["contact"] == contact
                )
                or client.get("email", "").casefold() == normalized_email
            )
        ),
        None,
    )
    if duplicate is not None:
        print(
            f"An active profile already exists for {duplicate['name']} "
            f"({duplicate['client_id']}). Client was not added."
        )
        return

    record = {
        "client_id": next_client_id(data["clients"]),
        "name": name,
        "contact": contact,
        "email": email,
        "membership": prompt_required("Membership plan: "),
        "created_at": current_timestamp(),
        "archived_at": "",
    }
    print(
        "\nNew client details:\n"
        f"  Name: {record['name']}\n"
        f"  Contact: {record['contact']}\n"
        f"  Email: {record['email']}\n"
        f"  Membership: {record['membership']}"
    )
    confirmation = input("Are you sure you want to add this client? (y/N): ")
    if confirmation.strip().lower() != "y":
        print("Client profile creation cancelled.")
        return

    save_record(connection, data, "clients", record)
    print(f"Client profile saved. Client ID: {record['client_id']}")


def update_client_profile(
    data: dict[str, list[dict[str, str]]],
    connection: mysql.connector.MySQLConnection,
) -> None:
    show_clients(data)
    print("\nUPDATE CLIENT PROFILE")
    client = select_client(data)
    if client is None:
        return

    print("Press Enter to keep the current value.")
    name = input(f"Full name [{client['name']}]: ").strip() or client["name"]
    contact = prompt_phone(
        "Contact number (Enter to keep): ",
        current=client["contact"],
    )
    email = input(f"Email address [{client.get('email', '')}] (Enter to keep): ").strip()
    if email:
        while not EMAIL_PATTERN.fullmatch(email):
            print("Enter a valid email address.")
            email = input("Email address: ").strip()
    else:
        email = client.get("email", "")
    membership = input(
        f"Membership plan [{client['membership']}]: "
    ).strip() or client["membership"]

    normalized_name = " ".join(name.casefold().split())
    normalized_email = email.casefold()
    duplicate = next(
        (
            existing
            for existing in data["clients"]
            if existing["client_id"] != client["client_id"]
            and not existing.get("archived_at")
            and (
                (
                    " ".join(existing["name"].casefold().split()) == normalized_name
                    and existing["contact"] == contact
                )
                or (
                    normalized_email
                    and existing.get("email", "").casefold() == normalized_email
                )
            )
        ),
        None,
    )
    if duplicate is not None:
        print(
            f"An active profile already exists for {duplicate['name']} "
            f"({duplicate['client_id']}). Client was not updated."
        )
        return

    print(
        "\nNew client details:\n"
        f"  Name: {name}\n"
        f"  Contact: {contact}\n"
        f"  Email: {email}\n"
        f"  Membership: {membership}"
    )
    confirmation = input(
        f"Are you sure you want to update client {client['client_id']}? (y/N): "
    ).strip().lower()
    if confirmation != "y":
        print("Update cancelled.")
        return

    if update_client(
        connection,
        client["client_id"],
        name,
        contact,
        email,
        membership,
    ):
        client.update(name=name, contact=contact, email=email, membership=membership)
        print(f"Client profile {client['client_id']} updated.")
    else:
        print("That client is no longer active.")


def log_attendance(
    data: dict[str, list[dict[str, str]]],
    connection: mysql.connector.MySQLConnection,
) -> None:
    print("\nLOG CLIENT ATTENDANCE")
    show_clients(data)
    client = select_client(data)
    if client is None:
        return

    timestamp = current_timestamp()
    if has_attendance_on_date(connection, client["client_id"], timestamp[:10]):
        print(
            f"Attendance is already logged for {client['name']} today. "
            "A client can only have one attendance record per day."
        )
        return

    record = {
        "client_id": client["client_id"],
        "client_name": client["name"],
        "email": client["email"],
        "timestamp": timestamp,
    }
    save_record(connection, data, "attendance", record)
    print(f"Attendance logged for {client['name']}.")


def show_attendance_records(data: dict[str, list[dict[str, str]]]) -> None:
    attendance = data["attendance"]
    print("\nATTENDANCE RECORDS")
    if not attendance:
        print("No attendance records found.")
        return

    columns = ("Client ID", "Client Name", "Email", "Date", "Time")
    rows = []
    for record in attendance:
        date, time = format_attendance_datetime(record["timestamp"])
        rows.append(
            (
                record["client_id"],
                record["client_name"],
                record.get("email", ""),
                date,
                time,
            )
        )
    widths = [
        max(len(columns[index]), *(len(row[index]) for row in rows))
        for index in range(len(columns))
    ]

    def format_row(values: tuple[str, ...]) -> str:
        return "| " + " | ".join(
            value.ljust(widths[index]) for index, value in enumerate(values)
        ) + " |"

    separator = "+-" + "-+-".join("-" * width for width in widths) + "-+"
    print(separator)
    print(format_row(columns))
    print(separator)
    for row in rows:
        print(format_row(row))
    print(separator)


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


def delete_client_record(
    data: dict[str, list[dict[str, str]]],
    connection: mysql.connector.MySQLConnection,
) -> None:
    show_clients(data)
    print("\nDELETE CLIENT RECORD (ARCHIVE)")
    client = select_client(data)
    if client is None:
        return

    confirmation = input(
        f"Archive {client['name']} ({client['client_id']})? (y/N): "
    ).strip().lower()
    if confirmation != "y":
        print("Archive cancelled.")
        return

    archived_at = current_timestamp()
    if archive_client(connection, client["client_id"], archived_at):
        client["archived_at"] = archived_at
        print(f"Client {client['client_id']} archived.")
    else:
        print("That client is no longer active.")


def display_archived_clients_table(
    archived_clients: list[dict[str, str]],
) -> None:
    print("\nARCHIVED CLIENTS")
    if not archived_clients:
        print("No archived clients found.")
        return

    columns = (
        "Client ID",
        "Name",
        "Contact",
        "Email",
        "Membership",
        "Created At",
        "Archived At",
    )
    rows = [
        (
            client["client_id"],
            client["name"],
            client["contact"],
            client["email"],
            client["membership"],
            format_created_at(client["created_at"]),
            format_created_at(client["archived_at"]),
        )
        for client in archived_clients
    ]
    widths = [
        max(len(columns[index]), *(len(row[index]) for row in rows))
        for index in range(len(columns))
    ]
    separator = "+-" + "-+-".join("-" * width for width in widths) + "-+"

    def format_row(values: tuple[str, ...]) -> str:
        return "| " + " | ".join(
            value.ljust(widths[index]) for index, value in enumerate(values)
        ) + " |"

    print(separator)
    print(format_row(columns))
    print(separator)
    for row in rows:
        print(format_row(row))
    print(separator)


def show_archived_clients(
    connection: mysql.connector.MySQLConnection,
) -> None:
    archived_clients = load_archived_clients(connection)
    display_archived_clients_table(archived_clients)

    input("\nPress Enter to return to the Client Records menu...")


def restore_archived_client(
    data: dict[str, list[dict[str, str]]],
    connection: mysql.connector.MySQLConnection,
) -> None:
    print("\nRESTORE ARCHIVED CLIENT")
    archived_clients = load_archived_clients(connection)
    if not archived_clients:
        print("There are no archived clients to restore.")
        return

    display_archived_clients_table(archived_clients)

    client_id = prompt_required("Enter client ID to restore: ").upper()
    client = next(
        (
            archived
            for archived in archived_clients
            if archived["client_id"].upper() == client_id
        ),
        None,
    )
    if client is None:
        print("No archived client found with that ID.")
        return

    confirmation = input(
        f"Are you sure you want to restore {client['name']} ({client['client_id']})? (y/N): "
    ).strip().lower()
    if confirmation != "y":
        print("Restore cancelled.")
        return

    if restore_client(connection, client["client_id"]):
        for existing_client in data["clients"]:
            if existing_client["client_id"] == client["client_id"]:
                existing_client["archived_at"] = ""
                break
        print(f"Client {client['client_id']} restored.")
    else:
        print("That client is no longer archived.")


def client_records_menu(
    data: dict[str, list[dict[str, str]]],
    connection: mysql.connector.MySQLConnection,
) -> None:
    actions = (
        lambda: update_client_profile(data, connection),
        lambda: delete_client_record(data, connection),
        lambda: restore_archived_client(data, connection),
        lambda: show_archived_clients(connection),
    )
    options = (
        "Update client profile",
        "Delete client profile",
        "Restore archived client",
        "View archived clients",
    )
    while True:
        show_clients(data)
        print("\nCLIENT RECORDS MENU")
        for number, option in enumerate(options, start=1):
            print(f"  {number}. {option}")
        print(f"  {len(actions) + 1}. Back to main menu")

        choice = input("\nChoose an option: ").strip()
        if choice == str(len(actions) + 1):
            return
        if not choice.isdigit() or not 1 <= int(choice) <= len(actions):
            print(f"Invalid option. Choose a number from 1 to {len(actions) + 1}.")
            continue

        try:
            actions[int(choice) - 1]()
        except mysql.connector.Error as error:
            print(f"Could not update MySQL records: {error}")


def show_menu(
    data: dict[str, list[dict[str, str]]],
    connection: mysql.connector.MySQLConnection,
) -> None:
    actions = (
        lambda records: client_records_menu(records, connection),
        lambda records: add_client(records, connection),
        show_attendance_records,
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
        print(f"  {len(actions) + 1}. Logout")

        choice = input("\nChoose an option: ").strip()
        if choice == str(len(actions) + 1):
            print("Logged out. Goodbye!")
            return

        if not choice.isdigit() or not 1 <= int(choice) <= len(actions):
            print(
                f"Invalid option. Please choose a number from 1 to "
                f"{len(actions) + 1}."
            )
            continue

        try:
            actions[int(choice) - 1](data)
        except mysql.connector.Error as error:
            print(f"Could not update MySQL records: {error}")


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
