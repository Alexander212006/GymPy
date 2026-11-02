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
            "(client_id, name, contact, email, membership, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s)"
        )
        values = (
            record["client_id"],
            record["name"],
            record["contact"],
            record["email"],
            record["membership"],
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
            "SELECT client_id, name, contact, email, membership, created_at, "
            "COALESCE(archived_at, '') AS archived_at "
            "FROM clients ORDER BY id"
        ),
        "attendance": (
            "SELECT client_id, client_name, timestamp "
            "FROM attendance ORDER BY id"
        ),
        "payments": (
            "SELECT client_id, client_name, amount, description, timestamp "
            "FROM payments ORDER BY id"
        ),
        "maintenance": (
            "SELECT machine, description, cost, timestamp "
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
            "SELECT client_id, name, contact, email, membership, "
            "created_at, archived_at "
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


def save_record(
    connection: mysql.connector.MySQLConnection,
    data: dict[str, list[dict[str, str]]],
    collection: str,
    record: dict[str, str],
) -> None:
    cursor = connection.cursor()
    try:
        _insert_record(cursor, collection, record)
        connection.commit()
    except mysql.connector.Error:
        connection.rollback()
        raise
    finally:
        cursor.close()
    data[collection].append(record)


def update_client(
    connection: mysql.connector.MySQLConnection,
    client_id: str,
    name: str,
    contact: str,
    email: str,
    membership: str,
) -> bool:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "UPDATE clients SET name = %s, contact = %s, email = %s, "
            "membership = %s "
            "WHERE client_id = %s AND archived_at IS NULL",
            (name, contact, email, membership, client_id),
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
