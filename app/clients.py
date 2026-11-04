import mysql.connector

from API import send_client_welcome_email
from database.queries import (
    archive_client,
    load_archived_clients,
    restore_client,
    save_record,
    update_client,
)

from .common import (
    EMAIL_PATTERN,
    client_is_member,
    current_timestamp,
    format_created_at,
    next_client_id,
    prompt_email,
    prompt_required,
    prompt_yes_no,
    select_client,
)

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
        "Valid ID Number",
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
            client.get("valid_id_number", ""),
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
                    client.get("valid_id_number", ""),
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
        record["valid_id_number"] = prompt_required(
            "Valid PWD/Student ID number: "
        )
    else:
        record["valid_id_number"] = ""

    print(
        "\nNew client details:\n"
        f"  Name: {record['name']}\n"
        f"  Email: {record['email']}\n"
        f"  PWD: {'Yes' if record['is_pwd'] == '1' else 'No'}\n"
        f"  Student: {'Yes' if record['is_student'] == '1' else 'No'}\n"
        f"  Worker: {'Yes' if record['is_worker'] == '1' else 'No'}"
        + (
            f"\n  Valid ID number: {record['valid_id_number']}"
            if record["valid_id_number"]
            else ""
        )
    )
    confirmation = input("Are you sure you want to add this client? (y/N): ")
    if confirmation.strip().lower() != "y":
        print("Client profile creation cancelled.")
        return

    save_record(connection, data, "clients", record)
    print(f"Client profile saved. Client ID: {record['client_id']}")
    try:
        send_client_welcome_email(record)
    except RuntimeError as error:
        print(f"Welcome email could not be sent: {error}")
    else:
        print(f"Welcome email sent to {record['email']}.")

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
    is_pwd = str(
        int(
            prompt_yes_no(
                "Is the client a PWD?",
                current=client.get("is_pwd", "0").lower() in {"1", "true"},
            )
        )
    )
    is_student = str(
        int(
            prompt_yes_no(
                "Is the client a Student?",
                current=client.get("is_student", "0").lower() in {"1", "true"},
            )
        )
    )
    if is_pwd == "1" or is_student == "1":
        current_id_number = client.get("valid_id_number", "").strip()
        if current_id_number:
            valid_id_number = (
                input(
                    f"Valid PWD/Student ID number [{current_id_number}] "
                    "(Enter to keep): "
                ).strip()
                or current_id_number
            )
        else:
            valid_id_number = prompt_required(
                "Valid PWD/Student ID number: "
            )
    else:
        valid_id_number = ""
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
        f"  PWD: {'Yes' if is_pwd == '1' else 'No'}\n"
        f"  Student: {'Yes' if is_student == '1' else 'No'}\n"
        f"  Valid ID number: {valid_id_number}\n"
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
        is_pwd,
        is_student,
        is_worker,
        valid_id_number,
    ):
        client.update(
            name=name,
            email=email,
            membership=membership,
            is_pwd=is_pwd,
            is_student=is_student,
            is_worker=is_worker,
            valid_id_number=valid_id_number,
        )
        print(f"Client profile {client['client_id']} updated.")
    else:
        print("That client is no longer active.")

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
        "Valid ID Number",
        "is_member",
        "Created At",
        "Archived At",
    )
    rows = [
        (
            client["client_id"],
            client["name"],
            client["email"],
            client.get("valid_id_number", ""),
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
