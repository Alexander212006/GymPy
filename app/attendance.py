import mysql.connector

from database.queries import has_attendance_on_date, save_record

from .common import current_timestamp, format_attendance_datetime, select_client
from .clients import show_clients

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
