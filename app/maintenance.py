import mysql.connector

from database.queries import save_record, update_maintenance_record

from .common import current_timestamp, format_created_at, prompt_amount, prompt_required

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
        print("  2. Edit maintenance record")
        print("  3. Back to main menu")
        choice = input("\nChoose an option: ").strip()
        if choice == "3":
            return
        if choice == "1":
            break
        if choice == "2":
            edit_maintenance_record(data, connection)
            return
        print("Invalid option. Choose 1, 2, or 3.")

    print("\nMACHINE MAINTENANCE RECORD")
    record = {
        "machine": prompt_required("Machine or equipment name: "),
        "description": prompt_required("Maintenance performed: "),
        "cost": prompt_amount("Maintenance cost (enter 0 if none): ", allow_zero=True),
        "timestamp": current_timestamp(),
    }
    save_record(connection, data, "maintenance", record)
    print(f"Maintenance record saved for {record['machine']}.")

def edit_maintenance_record(
    data: dict[str, list[dict[str, str]]],
    connection: mysql.connector.MySQLConnection,
) -> None:
    if not data["maintenance"]:
        print("There are no maintenance records to edit.")
        return

    record_id = prompt_required("Enter maintenance record ID to edit: ")
    record = next(
        (item for item in data["maintenance"] if item["id"] == record_id),
        None,
    )
    if record is None:
        print(f"No maintenance record found with ID {record_id}.")
        return

    print("Press Enter to keep the current value.")
    machine = input(f"Machine or equipment name [{record['machine']}]: ").strip()
    machine = machine or record["machine"]
    description = input(
        f"Maintenance performed [{record['description']}]: "
    ).strip() or record["description"]
    cost = prompt_amount(
        f"Maintenance cost [{record['cost']}]: ",
        allow_zero=True,
        current=record["cost"],
    )

    print(
        "\nUpdated maintenance details:\n"
        f"  Record ID: {record_id}\n"
        f"  Machine: {machine}\n"
        f"  Maintenance performed: {description}\n"
        f"  Cost: PHP {cost}\n"
        f"  Last serviced: {format_created_at(record['timestamp'])}"
    )
    confirmation = input("Save these changes? (y/N): ").strip().lower()
    if confirmation not in {"y", "yes"}:
        print("Maintenance record update cancelled.")
        return

    if update_maintenance_record(
        connection,
        record_id,
        machine,
        description,
        cost,
    ):
        record.update(machine=machine, description=description, cost=cost)
        print(f"Maintenance record {record_id} updated.")
    else:
        print(f"Maintenance record {record_id} no longer exists.")
