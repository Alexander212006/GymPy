from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import re

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

def prompt_amount(
    label: str,
    *,
    allow_zero: bool = False,
    current: str | None = None,
) -> str:
    while True:
        entered_amount = input(label).strip()
        if not entered_amount and current is not None:
            return current
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
