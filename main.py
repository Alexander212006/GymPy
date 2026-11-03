import getpass
import re
from datetime import datetime, timedelta
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
MEMBERSHIP_FEES = {"student_pwd": 200, "regular": 300}
SESSION_FEES = {
    "student_pwd": {"Full month session": 350, "Half month session": 600, "Daily session": 50},
    "regular": {"Full month session": 400, "Half month session": 750, "Daily session": 60},
    "non_member_student": {"Daily session": 60},
    "non_member_worker": {"Daily session": 80},
}
SESSION_VALIDITY = {
    "Full month session": timedelta(days=30),
    "Half month session": timedelta(days=15),
    "Daily session": timedelta(days=1),
}
MENU_OPTIONS = (
    "Client records",
    "Add client profile",
    "Attendance records",
    "Log client attendance",
    "Available services",
    "Payment history",
    "View active sessions",
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


def prompt_yes_no(label: str, *, current: bool | None = None) -> bool:
    prompt = f"{label} (y/n): "
    if current is not None:
        prompt = f"{label} [{'Y' if current else 'N'}] (Enter to keep): "
    while True:
        answer = input(prompt).strip().lower()
        if not answer and current is not None:
            return current
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Enter y or n.")


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


def client_is_member(
    payments: list[dict[str, str]],
    client_id: str,
) -> bool:
    return any(
        payment["client_id"] == client_id
        and payment["description"].casefold() == "gym membership"
        for payment in payments
    )


def active_session_payment(
    payments: list[dict[str, str]],
    client_id: str,
    now: datetime,
) -> tuple[dict[str, str], datetime] | None:
    for payment in reversed(payments):
        validity = SESSION_VALIDITY.get(payment["description"])
        if payment["client_id"] != client_id or validity is None:
            continue

        purchased_at = datetime.fromisoformat(payment["timestamp"])
        if purchased_at.tzinfo is None:
            purchased_at = purchased_at.astimezone()
        expires_at = purchased_at + validity
        if now < expires_at:
            return payment, expires_at
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


def show_clients(
    data: dict[str, list[dict[str, str]]],
    clients: list[dict[str, str]] | None = None,
) -> None:
    if clients is None:
        clients = [
            client for client in data["clients"] if not client.get("archived_at")
        ]
    print("\nCLIENT RECORDS")
    if not clients:
        print("No active client profiles found.")
        return

    columns = (
        "Client ID",
        "Name",
        "Email",
        "is_member",
        "Student",
        "PWD",
        "Worker",
        "Created At",
    )
    rows = [
        (
            client["client_id"],
            client["name"],
            client["email"],
            "Yes" if client_is_member(data["payments"], client["client_id"]) else "No",
            "Yes" if client.get("is_student", "").lower() in {"1", "true"} else "No",
            "Yes" if client.get("is_pwd", "").lower() in {"1", "true"} else "No",
            "Yes" if client.get("is_worker", "").lower() in {"1", "true"} else "No",
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
                    client["email"],
                    "Yes"
                    if client_is_member(data["payments"], client["client_id"])
                    else "No",
                    "Yes" if client.get("is_student", "").lower() in {"1", "true"} else "No",
                    "Yes" if client.get("is_pwd", "").lower() in {"1", "true"} else "No",
                    "Yes" if client.get("is_worker", "").lower() in {"1", "true"} else "No",
                    format_created_at(client["created_at"]),
                )
            )
        )
    print(separator)


def search_client_profile(data: dict[str, list[dict[str, str]]]) -> None:
    query = prompt_required("Search by client ID, name, or email: ").casefold()
    matches = [
        client
        for client in data["clients"]
        if not client.get("archived_at")
        and any(
            query in client.get(field, "").casefold()
            for field in ("client_id", "name", "email")
        )
    ]
    if not matches:
        print("No active client profiles matched your search.")
        return
    print(f"\nFound {len(matches)} matching client profile(s).")
    show_clients(data, matches)


def add_client(
    data: dict[str, list[dict[str, str]]],
    connection: mysql.connector.MySQLConnection,
) -> None:
    show_clients(data)

    print("\nADD CLIENT PROFILE")
    name = prompt_required("Full name: ")
    email = prompt_email()

    normalized_email = email.casefold()
    duplicate = next(
        (
            client
            for client in data["clients"]
            if not client.get("archived_at")
            and client.get("email", "").casefold() == normalized_email
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
        "email": email,
        "membership": "",
        "is_pwd": str(int(prompt_yes_no("Is the client a PWD?"))),
        "is_student": str(int(prompt_yes_no("Is the client a Student?"))),
        "is_worker": str(int(prompt_yes_no("Is the client a Worker?"))),
        "created_at": current_timestamp(),
        "archived_at": "",
    }
    if record["is_pwd"] == "1" or record["is_student"] == "1":
        record["id_number"] = prompt_required("PWD/Student ID number: ")
    else:
        record["id_number"] = ""

    print(
        "\nNew client details:\n"
        f"  Name: {record['name']}\n"
        f"  Email: {record['email']}\n"
        "  Membership: Not set\n"
        f"  PWD: {'Yes' if record['is_pwd'] == '1' else 'No'}\n"
        f"  Student: {'Yes' if record['is_student'] == '1' else 'No'}\n"
        f"  Worker: {'Yes' if record['is_worker'] == '1' else 'No'}"
        + (
            f"\n  ID number: {record['id_number']}"
            if record["id_number"]
            else ""
        )
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
    is_worker = str(
        int(
            prompt_yes_no(
                "Is the client a Worker?",
                current=client.get("is_worker", "0").lower() in {"1", "true"},
            )
        )
    )

    normalized_email = email.casefold()
    duplicate = next(
        (
            existing
            for existing in data["clients"]
            if existing["client_id"] != client["client_id"]
            and not existing.get("archived_at")
            and (
                normalized_email
                and existing.get("email", "").casefold() == normalized_email
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
        f"  Email: {email}\n"
        f"  Membership: {membership}\n"
        f"  Worker: {'Yes' if is_worker == '1' else 'No'}"
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
        email,
        membership,
        is_worker,
    ):
        client.update(name=name, email=email, membership=membership, is_worker=is_worker)
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
    description: str,
) -> None:
    print(f"\n{description.upper()}")
    clients = [
        client for client in data["clients"] if not client.get("archived_at")
    ]
    if not clients:
        print("There are no active client profiles. Add a client profile first.")
        return

    columns = (
        "Client ID",
        "Full Name",
        "is_member",
        "Student",
        "PWD",
        "Worker",
        "ID Number",
    )
    rows = [
        (
            client["client_id"],
            client["name"],
            "Yes" if client_is_member(data["payments"], client["client_id"]) else "No",
            "Yes" if client.get("is_student", "").lower() in {"1", "true"} else "No",
            "Yes" if client.get("is_pwd", "").lower() in {"1", "true"} else "No",
            "Yes" if client.get("is_worker", "").lower() in {"1", "true"} else "No",
            client.get("id_number", ""),
        )
        for client in clients
    ]
    widths = [
        max(len(columns[index]), *(len(row[index]) for row in rows))
        for index in range(len(columns))
    ]

    def format_row(values: tuple[str, ...]) -> str:
        return "| " + " | ".join(
            values[index].ljust(widths[index]) for index in range(len(values))
        ) + " |"

    separator = "+-" + "-+-".join("-" * width for width in widths) + "-+"
    print(separator)
    print(format_row(columns))
    print(separator)
    for row in rows:
        print(format_row(row))
    print(separator)

    client = select_client(data)
    if client is None:
        return

    now = datetime.now().astimezone()
    try:
        active_session = active_session_payment(
            data["payments"],
            client["client_id"],
            now,
        )
    except ValueError as error:
        print(f"Could not verify this client's service validity: {error}")
        return
    if active_session is not None:
        active_payment, expires_at = active_session
        print(
            f"{client['name']} already has an active "
            f"{active_payment['description']} until "
            f"{expires_at.strftime('%Y-%m-%d %I:%M %p %Z')}. "
            "No additional service can be purchased until it expires."
        )
        return

    is_student = client.get("is_student", "").lower() in {"1", "true"}
    is_pwd = client.get("is_pwd", "").lower() in {"1", "true"}
    is_worker = client.get("is_worker", "").lower() in {"1", "true"}
    is_member = client_is_member(data["payments"], client["client_id"])

    if description == "Gym membership":
        if is_member:
            print("This client has already purchased a gym membership.")
            return
        category = "student_pwd" if is_student or is_pwd else "regular"
        amount = MEMBERSHIP_FEES[category]
        discount_amount = MEMBERSHIP_FEES["regular"] - amount
    elif is_member:
        category = "student_pwd" if is_student or is_pwd else "regular"
        amount = SESSION_FEES[category].get(description)
        regular_amount = SESSION_FEES["regular"].get(description)
        discount_amount = (
            regular_amount - amount
            if regular_amount is not None and amount is not None
            else 0
        )
    elif description == "Daily session" and is_student:
        amount = SESSION_FEES["non_member_student"][description]
        discount_amount = 0
    elif description == "Daily session" and is_worker:
        amount = SESSION_FEES["non_member_worker"][description]
        discount_amount = 0
    else:
        amount = None
        discount_amount = 0

    if amount is None:
        print(
            "This client is not eligible for that service. "
            "A gym membership is required for full or half month sessions; "
            "non-members may only purchase daily sessions if they are a "
            "student or worker."
        )
        return

    record = {
        "client_id": client["client_id"],
        "client_name": client["name"],
        "amount": f"{amount:.2f}",
        "description": description,
        "timestamp": current_timestamp(),
    }
    if is_pwd and is_student:
        discount = "PWD and Student"
    elif is_pwd:
        discount = "PWD"
    elif is_student:
        discount = "Student"
    else:
        discount = "None (regular rate)"

    print(
        f"\nPayment summary:\n"
        f"  Client: {client['name']} ({client['client_id']})\n"
        f"  Service: {description}\n"
        f"  Discount: {discount} (PHP {discount_amount:.2f})\n"
        f"  Amount due: PHP {record['amount']}"
    )
    confirmation = input("Confirm payment? (y/N): ").strip().lower()
    if confirmation not in {"y", "yes"}:
        print("Payment cancelled.")
        return

    save_record(connection, data, "payments", record)
    print(f"Payment of {record['amount']} recorded for {client['name']}.")


def membership_payment_menu(
    data: dict[str, list[dict[str, str]]],
    connection: mysql.connector.MySQLConnection,
) -> None:
    def print_rate_table(
        title: str,
        columns: tuple[str, ...],
        rows: tuple[tuple[str, ...], ...],
    ) -> None:
        widths = [
            max(len(columns[index]), *(len(row[index]) for row in rows))
            for index in range(len(columns))
        ]

        def format_row(values: tuple[str, ...]) -> str:
            return "| " + " | ".join(
                values[index].ljust(widths[index])
                for index in range(len(values))
            ) + " |"

        separator = "+-" + "-+-".join("-" * width for width in widths) + "-+"
        print(f"\n{title} (pesos)")
        print(separator)
        print(format_row(columns))
        print(separator)
        for row in rows:
            print(format_row(row))
        print(separator)

    membership_columns = ("Client category", "Membership fee")
    membership_rows = (
        ("Student/PWD", str(MEMBERSHIP_FEES["student_pwd"])),
        ("Regular customer", str(MEMBERSHIP_FEES["regular"])),
    )
    rate_columns = (
        "Client category",
        "Full month",
        "Half month",
        "Daily session",
    )
    rate_rows = (
        (
            "Student/PWD member",
            str(SESSION_FEES["student_pwd"]["Full month session"]),
            str(SESSION_FEES["student_pwd"]["Half month session"]),
            str(SESSION_FEES["student_pwd"]["Daily session"]),
        ),
        (
            "Regular member",
            str(SESSION_FEES["regular"]["Full month session"]),
            str(SESSION_FEES["regular"]["Half month session"]),
            str(SESSION_FEES["regular"]["Daily session"]),
        ),
        (
            "Non-member (student)",
            "N/A",
            "N/A",
            str(SESSION_FEES["non_member_student"]["Daily session"]),
        ),
        (
            "Non-member (worker)",
            "N/A",
            "N/A",
            str(SESSION_FEES["non_member_worker"]["Daily session"]),
        ),
    )

    options = (
        "Gym membership",
        "Full month session",
        "Half month session",
        "Daily session",
    )
    while True:
        print_rate_table("MEMBERSHIP FEES", membership_columns, membership_rows)
        print_rate_table("SERVICE RATES", rate_columns, rate_rows)
        print("\nAvailable Services")
        for number, option in enumerate(options, start=1):
            print(f"  {number}. {option}")
        print(f"  {len(options) + 1}. Back to main menu")

        choice = input("\nChoose an option: ").strip()
        if choice == str(len(options) + 1):
            return
        if not choice.isdigit() or not 1 <= int(choice) <= len(options):
            print(f"Invalid option. Choose a number from 1 to {len(options) + 1}.")
            continue

        record_payment(data, connection, options[int(choice) - 1])
        return


def show_payment_history(data: dict[str, list[dict[str, str]]]) -> None:
    payments = data["payments"]
    print("\nPAYMENT HISTORY")
    if not payments:
        print("No payments recorded.")
        return

    columns = (
        "Date",
        "Time",
        "Client ID",
        "Client Name",
        "Amount (PHP)",
        "Description",
    )
    rows = [
        (
            *format_attendance_datetime(payment["timestamp"]),
            payment["client_id"],
            payment["client_name"],
            payment["amount"],
            payment["description"],
        )
        for payment in payments
    ]
    widths = [
        max(len(columns[index]), *(len(row[index]) for row in rows))
        for index in range(len(columns))
    ]

    def format_row(values: tuple[str, ...]) -> str:
        return "| " + " | ".join(
            values[index].ljust(widths[index]) for index in range(len(values))
        ) + " |"

    separator = "+-" + "-+-".join("-" * width for width in widths) + "-+"
    print(separator)
    print(format_row(columns))
    print(separator)
    for row in rows:
        print(format_row(row))
    print(separator)


def show_active_sessions(data: dict[str, list[dict[str, str]]]) -> None:
    now = datetime.now().astimezone()
    rows = []
    for client in data["clients"]:
        try:
            active_session = active_session_payment(
                data["payments"],
                client["client_id"],
                now,
            )
        except ValueError as error:
            print(
                f"Could not check the session for {client['client_id']}: {error}"
            )
            return
        if active_session is None:
            continue

        payment, expires_at = active_session
        purchased_at = datetime.fromisoformat(payment["timestamp"])
        if purchased_at.tzinfo is None:
            purchased_at = purchased_at.astimezone()
        rows.append(
            (
                client["client_id"],
                client["name"],
                payment["description"],
                purchased_at.astimezone().strftime("%B %d, %Y %I:%M %p"),
                expires_at.astimezone().strftime("%B %d, %Y %I:%M %p"),
            )
        )

    print("\nACTIVE SESSIONS")
    if not rows:
        print("No active sessions.")
        return

    columns = ("Client ID", "Client Name", "Session", "Availed At", "Ends At")
    widths = [
        max(len(columns[index]), *(len(row[index]) for row in rows))
        for index in range(len(columns))
    ]

    def format_row(values: tuple[str, ...]) -> str:
        return "| " + " | ".join(
            values[index].ljust(widths[index]) for index in range(len(values))
        ) + " |"

    separator = "+-" + "-+-".join("-" * width for width in widths) + "-+"
    print(separator)
    print(format_row(columns))
    print(separator)
    for row in rows:
        print(format_row(row))
    print(separator)


def record_maintenance(
    data: dict[str, list[dict[str, str]]],
    connection: mysql.connector.MySQLConnection,
) -> None:
    print("\nMACHINE MAINTENANCE HISTORY")
    maintenance_records = data["maintenance"]
    if not maintenance_records:
        print("No maintenance records found.")
    else:
        columns = (
            "ID",
            "Last Serviced",
            "Machine",
            "Maintenance Performed",
            "Cost (PHP)",
        )
        rows = [
            (
                record["id"],
                format_created_at(record["timestamp"]),
                record["machine"],
                record["description"],
                record["cost"],
            )
            for record in maintenance_records
        ]
        widths = [
            max(len(columns[index]), *(len(row[index]) for row in rows))
            for index in range(len(columns))
        ]

        def format_row(values: tuple[str, ...]) -> str:
            return "| " + " | ".join(
                values[index].ljust(widths[index])
                for index in range(len(values))
            ) + " |"

        separator = "+-" + "-+-".join("-" * width for width in widths) + "-+"
        print(separator)
        print(format_row(columns))
        print(separator)
        for row in rows:
            print(format_row(row))
        print(separator)

    while True:
        print("\nMAINTENANCE OPTIONS")
        print("  1. Add maintenance record")
        print("  2. Back to main menu")
        choice = input("\nChoose an option: ").strip()
        if choice == "2":
            return
        if choice == "1":
            break
        print("Invalid option. Choose 1 or 2.")

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
    payments: list[dict[str, str]],
) -> None:
    print("\nARCHIVED CLIENTS")
    if not archived_clients:
        print("No archived clients found.")
        return

    columns = (
        "Client ID",
        "Name",
        "Email",
        "is_member",
        "Created At",
        "Archived At",
    )
    rows = [
        (
            client["client_id"],
            client["name"],
            client["email"],
            "Yes" if client_is_member(payments, client["client_id"]) else "No",
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
    data: dict[str, list[dict[str, str]]],
    connection: mysql.connector.MySQLConnection,
) -> None:
    archived_clients = load_archived_clients(connection)
    display_archived_clients_table(archived_clients, data["payments"])

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

    display_archived_clients_table(archived_clients, data["payments"])

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
        lambda: search_client_profile(data),
        lambda: update_client_profile(data, connection),
        lambda: delete_client_record(data, connection),
        lambda: restore_archived_client(data, connection),
        lambda: show_archived_clients(data, connection),
    )
    options = (
        "Search client profile",
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
        lambda records: membership_payment_menu(records, connection),
        show_payment_history,
        show_active_sessions,
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
