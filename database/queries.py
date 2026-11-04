from decimal import Decimal

import mysql.connector


def _insert_record(
    cursor: mysql.connector.cursor.MySQLCursor,
    collection: str,
    record: dict[str, str],
) -> None:
    if collection == "clients":
        statement = (
            "INSERT INTO clients "
            "(client_id, name, email, is_member, is_pwd, "
            "is_student, is_worker, valid_id_number, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
        )
        values = (
            record["client_id"],
            record["name"],
            record["email"],
            record["is_member"],
            record["is_pwd"],
            record["is_student"],
            record["is_worker"],
            record["valid_id_number"],
            record["created_at"],
        )
    elif collection == "attendance":
        statement = (
            "INSERT INTO attendance (client_id, client_name, timestamp) "
            "VALUES (%s, %s, %s)"
        )
        values = (record["client_id"], record["client_name"], record["timestamp"])
    elif collection == "payments":
        statement = (
            "INSERT INTO payments "
            "(client_id, client_name, amount, description, timestamp) "
            "VALUES (%s, %s, %s, %s, %s)"
        )
        values = (
            record["client_id"],
            record["client_name"],
            record["amount"],
            record["description"],
            record["timestamp"],
        )
    elif collection == "maintenance":
        statement = (
            "INSERT INTO maintenance (machine, description, cost, timestamp) "
            "VALUES (%s, %s, %s, %s)"
        )
        values = (
            record["machine"],
            record["description"],
            record["cost"],
            record["timestamp"],
        )
    else:
        raise ValueError(f"Unknown data collection: {collection}")
    cursor.execute(statement, values)


def load_data(
    connection: mysql.connector.MySQLConnection,
) -> dict[str, list[dict[str, str]]]:
    queries = {
        "clients": (
            "SELECT client_id, name, email, is_member, is_pwd, "
            "is_student, is_worker, valid_id_number, created_at, "
            "COALESCE(archived_at, '') AS archived_at "
            "FROM clients ORDER BY id"
        ),
        "attendance": (
            "SELECT attendance.client_id, attendance.client_name, "
            "COALESCE(clients.email, '') AS email, attendance.timestamp "
            "FROM attendance LEFT JOIN clients "
            "ON clients.client_id = attendance.client_id "
            "ORDER BY attendance.id"
        ),
        "payments": (
            "SELECT client_id, client_name, amount, description, timestamp "
            "FROM payments ORDER BY id"
        ),
        "maintenance": (
            "SELECT id, machine, description, cost, timestamp "
            "FROM maintenance ORDER BY id"
        ),
    }
    data: dict[str, list[dict[str, str]]] = {}
    cursor = connection.cursor(dictionary=True)
    try:
        for collection, query in queries.items():
            cursor.execute(query)
            records = cursor.fetchall()
            data[collection] = [
                {
                    key: format(value, ".2f")
                    if isinstance(value, Decimal)
                    else str(value)
                    for key, value in record.items()
                }
                for record in records
            ]
    finally:
        cursor.close()
    return data


def load_archived_clients(
    connection: mysql.connector.MySQLConnection,
) -> list[dict[str, str]]:
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT client_id, name, email, is_member, is_pwd, "
            "is_student, is_worker, valid_id_number, created_at, archived_at "
            "FROM clients WHERE archived_at IS NOT NULL ORDER BY id"
        )
        return [
            {
                key: format(value, ".2f")
                if isinstance(value, Decimal)
                else str(value)
                for key, value in record.items()
            }
            for record in cursor.fetchall()
        ]
    finally:
        cursor.close()


def has_attendance_on_date(
    connection: mysql.connector.MySQLConnection,
    client_id: str,
    attendance_date: str,
) -> bool:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT 1 FROM attendance "
            "WHERE client_id = %s AND timestamp LIKE %s LIMIT 1",
            (client_id, f"{attendance_date}%"),
        )
        return cursor.fetchone() is not None
    finally:
        cursor.close()


def save_record(
    connection: mysql.connector.MySQLConnection,
    data: dict[str, list[dict[str, str]]],
    collection: str,
    record: dict[str, str],
) -> None:
    cursor = connection.cursor()
    try:
        _insert_record(cursor, collection, record)
        if (
            collection == "payments"
            and record["description"].casefold() == "gym membership"
        ):
            cursor.execute(
                "UPDATE clients SET is_member = TRUE WHERE client_id = %s",
                (record["client_id"],),
            )
        if collection == "maintenance":
            record["id"] = str(cursor.lastrowid)
        connection.commit()
    except mysql.connector.Error:
        connection.rollback()
        raise
    finally:
        cursor.close()
    data[collection].append(record)
    if (
        collection == "payments"
        and record["description"].casefold() == "gym membership"
    ):
        for client in data["clients"]:
            if client["client_id"] == record["client_id"]:
                client["is_member"] = "1"
                break


def update_client(
    connection: mysql.connector.MySQLConnection,
    client_id: str,
    name: str,
    email: str,
    is_pwd: str,
    is_student: str,
    is_worker: str,
    valid_id_number: str,
) -> bool:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "UPDATE clients SET name = %s, email = %s, "
            "is_pwd = %s, is_student = %s, is_worker = %s, "
            "valid_id_number = %s "
            "WHERE client_id = %s AND archived_at IS NULL",
            (
                name,
                email,
                is_pwd,
                is_student,
                is_worker,
                valid_id_number,
                client_id,
            ),
        )
        if cursor.rowcount == 0:
            cursor.execute(
                "SELECT 1 FROM clients "
                "WHERE client_id = %s AND archived_at IS NULL",
                (client_id,),
            )
            if cursor.fetchone() is None:
                connection.rollback()
                return False
        connection.commit()
        return True
    except mysql.connector.Error:
        connection.rollback()
        raise
    finally:
        cursor.close()


def update_maintenance_record(
    connection: mysql.connector.MySQLConnection,
    record_id: str,
    machine: str,
    description: str,
    cost: str,
) -> bool:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "UPDATE maintenance SET machine = %s, description = %s, cost = %s "
            "WHERE id = %s",
            (machine, description, cost, record_id),
        )
        if cursor.rowcount == 0:
            cursor.execute("SELECT 1 FROM maintenance WHERE id = %s", (record_id,))
            if cursor.fetchone() is None:
                connection.rollback()
                return False
        connection.commit()
        return True
    except mysql.connector.Error:
        connection.rollback()
        raise
    finally:
        cursor.close()


def archive_client(
    connection: mysql.connector.MySQLConnection,
    client_id: str,
    archived_at: str,
) -> bool:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "UPDATE clients SET archived_at = %s "
            "WHERE client_id = %s AND archived_at IS NULL",
            (archived_at, client_id),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            return False
        connection.commit()
        return True
    except mysql.connector.Error:
        connection.rollback()
        raise
    finally:
        cursor.close()


def restore_client(
    connection: mysql.connector.MySQLConnection,
    client_id: str,
) -> bool:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "UPDATE clients SET archived_at = NULL "
            "WHERE client_id = %s AND archived_at IS NOT NULL",
            (client_id,),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            return False
        connection.commit()
        return True
    except mysql.connector.Error:
        connection.rollback()
        raise
    finally:
        cursor.close()
