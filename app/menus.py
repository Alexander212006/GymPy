import mysql.connector

from .attendance import log_attendance, show_attendance_records
from .clients import add_client, client_records_menu
from .employees import add_employee
from .maintenance import record_maintenance
from .payments import membership_payment_menu, show_active_sessions, show_payment_history

MENU_OPTIONS = (
    "Client records",
    "Add client profile",
    "Attendance records",
    "Log client attendance",
    "Available services",
    "Payment history",
    "View active sessions",
    "Machine maintenance record",
    "Add employee profile",
)


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
        lambda records: add_employee(records, connection),
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
