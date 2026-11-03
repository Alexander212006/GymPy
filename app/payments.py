from datetime import datetime

import mysql.connector

from database.queries import save_record

from .common import (
    MEMBERSHIP_FEES,
    SESSION_FEES,
    active_session_payment,
    client_is_member,
    current_timestamp,
    format_attendance_datetime,
    select_client,
)

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
