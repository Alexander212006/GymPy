import re

import mysql.connector

from database.queries import save_record

from .common import prompt_required


CONTACT_NUMBER_PATTERN = re.compile(r"09\d{9}")


def prompt_employee_name(
    connection: mysql.connector.MySQLConnection,
    prompt: str,
    current_name: str | None = None,
) -> str | None:
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT first_name, last_name FROM employees ORDER BY id")
        employees = cursor.fetchall()
    finally:
        cursor.close()

    if not employees:
        print("No employee profiles found. Add an employee profile first.")
        return None

    employees_by_name = {
        " ".join(f"{first_name} {last_name}".split()).casefold():
            " ".join(f"{first_name} {last_name}".split())
        for first_name, last_name in employees
    }
    current_key = " ".join((current_name or "").split()).casefold()
    while True:
        prompt_text = prompt
        if current_name:
            prompt_text = (
                f"{prompt.rstrip(': ')} [{current_name}] (Enter to keep): "
            )
        entered_name = " ".join(input(prompt_text).split())
        if not entered_name and current_key:
            employee_name = employees_by_name.get(current_key)
            if employee_name is not None:
                return employee_name
        if not entered_name:
            print("This field is required.")
            continue
        employee_name = employees_by_name.get(entered_name.casefold())
        if employee_name is not None:
            return employee_name
        print("No employee profile matches that name. Enter an existing employee name.")


def show_employee_table(data: dict[str, list[dict[str, str]]]) -> None:
    employees = data["employees"]
    print("\nEMPLOYEE PROFILES")
    if not employees:
        print("No employee profiles found.")
        return

    columns = (
        "First Name",
        "Last Name",
        "Contact Number",
        "Address",
        "Sex",
        "Age",
    )
    rows = [
        tuple(employee[field] for field in (
            "first_name",
            "last_name",
            "contact_number",
            "address",
            "sex",
            "age",
        ))
        for employee in employees
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
    for row in rows:
        print(format_row(row))
    print(separator)


def prompt_age() -> str:
    while True:
        age = prompt_required("Age: ")
        try:
            numeric_age = int(age)
        except ValueError:
            print("Enter age as a whole number from 18 to 50.")
            continue
        if 18 <= numeric_age <= 50:
            return str(numeric_age)
        print("Age must be from 18 to 50.")


def prompt_contact_number() -> str:
    while True:
        contact_number = prompt_required("Contact number (09XXXXXXXXX): ")
        if CONTACT_NUMBER_PATTERN.fullmatch(contact_number):
            return contact_number
        print("Enter an 11-digit contact number starting with 09.")


def add_employee(
    data: dict[str, list[dict[str, str]]],
    connection: mysql.connector.MySQLConnection,
) -> None:
    show_employee_table(data)
    print("\nADD EMPLOYEE PROFILE")
    record = {
        "first_name": prompt_required("First name: "),
        "last_name": prompt_required("Last name: "),
        "contact_number": prompt_contact_number(),
        "address": prompt_required("Address: "),
        "sex": prompt_required("Sex: "),
        "age": prompt_age(),
    }

    print(
        "\nEmployee details:\n"
        f"  Name: {record['first_name']} {record['last_name']}\n"
        f"  Contact number: {record['contact_number']}\n"
        f"  Address: {record['address']}\n"
        f"  Sex: {record['sex']}\n"
        f"  Age: {record['age']}"
    )
    confirmation = input("Are you sure you want to add this employee? (y/N): ")
    if confirmation.strip().lower() != "y":
        print("Employee profile creation cancelled.")
        return

    save_record(connection, data, "employees", record)
    print("Employee profile saved.")
