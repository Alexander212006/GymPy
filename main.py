import getpass
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path


LOGIN_PASSWORD = "gympy123"
MAX_ATTEMPTS = 3
DATA_FILE = Path(__file__).with_name("gym_data.json")
MENU_OPTIONS = (
    "Client records",
    "Add client profile",
    "Log client attendance",
    "Client payment",
    "Payment history",
    "Machine maintenance record",
)
DATA_COLLECTIONS = ("clients", "attendance", "payments", "maintenance")
REQUIRED_FIELDS = {
    "clients": {"client_id", "name", "contact", "membership", "created_at"},
    "attendance": {"client_id", "client_name", "timestamp"},
    "payments": {
        "client_id",
        "client_name",
        "amount",
        "description",
        "timestamp",
    },
    "maintenance": {"machine", "description", "cost", "timestamp"},
}


def load_data() -> dict[str, list[dict[str, str]]]:
    try:
        contents = DATA_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {collection: [] for collection in DATA_COLLECTIONS}

    try:
        data = json.loads(contents)
    except json.JSONDecodeError as error:
        raise ValueError(f"{DATA_FILE.name} contains invalid JSON.") from error

    if not isinstance(data, dict) or any(
        not isinstance(data.get(collection), list) for collection in DATA_COLLECTIONS
    ):
        raise ValueError(f"{DATA_FILE.name} has an invalid data structure.")
    if any(
        not isinstance(record, dict)
        or not REQUIRED_FIELDS[collection].issubset(record)
        or any(not isinstance(value, str) for value in record.values())
        for collection in DATA_COLLECTIONS
        for record in data[collection]
    ):
        raise ValueError(f"{DATA_FILE.name} contains an invalid record.")

    return {collection: data[collection] for collection in DATA_COLLECTIONS}


def save_record(
    data: dict[str, list[dict[str, str]]],
    collection: str,
    record: dict[str, str],
) -> None:
    updated_data = {**data, collection: [*data[collection], record]}
    DATA_FILE.write_text(
        json.dumps(updated_data, indent=2) + "\n",
        encoding="utf-8",
    )
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


def login() -> bool:
    for attempt in range(MAX_ATTEMPTS):
        entered_password = getpass.getpass("Enter password: ")
        if entered_password == LOGIN_PASSWORD:
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


def add_client(data: dict[str, list[dict[str, str]]]) -> None:
    print("\nADD CLIENT PROFILE")
    record = {
        "client_id": next_client_id(data["clients"]),
        "name": prompt_required("Full name: "),
        "contact": prompt_required("Contact number: "),
        "membership": prompt_required("Membership plan: "),
        "created_at": current_timestamp(),
    }
    save_record(data, "clients", record)
    print(f"Client profile saved. Client ID: {record['client_id']}")


def log_attendance(data: dict[str, list[dict[str, str]]]) -> None:
    print("\nLOG CLIENT ATTENDANCE")
    client = select_client(data)
    if client is None:
        return

    record = {
        "client_id": client["client_id"],
        "client_name": client["name"],
        "timestamp": current_timestamp(),
    }
    save_record(data, "attendance", record)
    print(f"Attendance logged for {client['name']}.")


def record_payment(data: dict[str, list[dict[str, str]]]) -> None:
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
    save_record(data, "payments", record)
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


def record_maintenance(data: dict[str, list[dict[str, str]]]) -> None:
    print("\nMACHINE MAINTENANCE RECORD")
    record = {
        "machine": prompt_required("Machine or equipment name: "),
        "description": prompt_required("Maintenance performed: "),
        "cost": prompt_amount("Maintenance cost (enter 0 if none): ", allow_zero=True),
        "timestamp": current_timestamp(),
    }
    save_record(data, "maintenance", record)
    print(f"Maintenance record saved for {record['machine']}.")


def show_menu(data: dict[str, list[dict[str, str]]]) -> None:
    actions = (
        show_clients,
        add_client,
        log_attendance,
        record_payment,
        show_payment_history,
        record_maintenance,
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
        except OSError as error:
            print(f"Could not save the record: {error}")


def main() -> None:
    show_welcome()
    if login():
        try:
            data = load_data()
        except (OSError, ValueError) as error:
            print(f"Could not load gym records: {error}")
            return
        show_menu(data)


if __name__ == "__main__":
    main()
