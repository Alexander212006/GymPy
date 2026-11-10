from contextlib import asynccontextmanager, contextmanager
from datetime import datetime
from decimal import Decimal
import re
from typing import AsyncGenerator, Generator, overload

import mysql.connector
from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
)

from API.brevo import send_client_welcome_email_once
from app.common import current_timestamp, next_client_id
from database.connection import connect_database, initialize_database


EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClientInput(APIModel):
    name: str = Field(min_length=1, max_length=255)
    email: str = Field(max_length=254)
    is_pwd: bool = False
    is_student: bool = False
    is_worker: bool = False
    valid_id_number: str = Field(
        default="",
        max_length=100,
        validate_default=True,
        validation_alias=AliasChoices("valid_id_number", "id_number"),
    )

    @field_validator(
        "name", "email", "valid_id_number", mode="before"
    )
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        if not value:
            raise ValueError("Name cannot be blank.")
        return value

    @field_validator("email")
    @classmethod
    def email_must_be_valid(cls, value: str) -> str:
        if not EMAIL_PATTERN.fullmatch(value):
            raise ValueError("Enter a valid email address.")
        return value

    @field_validator("valid_id_number")
    @classmethod
    def require_id_for_pwd_or_student(
        cls, value: str, info: ValidationInfo
    ) -> str:
        if (info.data.get("is_pwd") or info.data.get("is_student")) and not value:
            raise ValueError("PWD or student clients must provide a valid ID number.")
        return value


class AttendanceInput(APIModel):
    client_id: str = Field(min_length=1, max_length=20)
    timestamp: str | None = Field(default=None, max_length=40)

    @field_validator("client_id")
    @classmethod
    def strip_client_id(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("Client ID cannot be blank.")
        return value

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                datetime.fromisoformat(value)
            except ValueError as error:
                raise ValueError("Timestamp must be in ISO 8601 format.") from error
        return value


class AttendanceReplace(AttendanceInput):
    timestamp: str = Field(max_length=40)


class PaymentInput(APIModel):
    client_id: str = Field(min_length=1, max_length=20)
    amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    description: str = Field(min_length=1, max_length=255)

    @field_validator("client_id", "description", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("client_id")
    @classmethod
    def normalize_client_id(cls, value: str) -> str:
        value = value.upper()
        if not value:
            raise ValueError("Client ID cannot be blank.")
        return value

    @field_validator("description")
    @classmethod
    def description_must_not_be_blank(cls, value: str) -> str:
        if not value:
            raise ValueError("Description cannot be blank.")
        return value


class MaintenanceInput(APIModel):
    machine: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=255)
    cost: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    performed_by: str | None = Field(default=None, max_length=255)

    @field_validator("machine", "description", "performed_by", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


    @field_validator("machine", "description")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value:
            raise ValueError("Text fields cannot be blank.")
        return value


def _serialize(row: dict[str, object]) -> dict[str, object]:
    return {
        key: (
            format(value, ".2f")
            if isinstance(value, Decimal)
            else bool(value)
            if key in {"is_member", "is_pwd", "is_student", "is_worker"}
            else value
        )
        for key, value in row.items()
    }


@contextmanager
def _transaction(
    connection: mysql.connector.MySQLConnection,
) -> Generator[None, None, None]:
    try:
        yield
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def get_connection() -> Generator[mysql.connector.MySQLConnection, None, None]:
    connection = connect_database()
    try:
        yield connection
    finally:
        connection.close()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    connection = connect_database()
    try:
        initialize_database(connection)
    finally:
        connection.close()
    yield


app = FastAPI(
    title="GymPy API",
    description="Authenticated CRUD API for GymPy records.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(mysql.connector.Error)
async def handle_database_error(_, error: mysql.connector.Error) -> Response:
    if isinstance(error, mysql.connector.IntegrityError):
        return Response(
            content='{"detail":"The record conflicts with existing data."}',
            status_code=status.HTTP_409_CONFLICT,
            media_type="application/json",
        )
    return Response(
        content='{"detail":"The database is unavailable."}',
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        media_type="application/json",
    )


@app.get("/api/clients")
def list_clients(
    include_archived: bool = Query(default=False),
    connection: mysql.connector.MySQLConnection = Depends(get_connection),
) -> list[dict[str, object]]:
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT client_id, name, email, is_member, is_pwd, is_student, "
            "is_worker, valid_id_number, created_at, archived_at "
            "FROM clients WHERE (%s = TRUE OR archived_at IS NULL) "
            "ORDER BY id",
            (include_archived,),
        )
        return [_serialize(row) for row in cursor.fetchall()]
    finally:
        cursor.close()


@app.get("/api/clients/{client_id}")
def get_client(
    client_id: str,
    connection: mysql.connector.MySQLConnection = Depends(get_connection),
) -> dict[str, object]:
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT client_id, name, email, is_member, is_pwd, is_student, "
            "is_worker, valid_id_number, created_at, archived_at "
            "FROM clients WHERE client_id = %s",
            (client_id.upper(),),
        )
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Client not found.")
        return _serialize(row)
    finally:
        cursor.close()


def _ensure_unique_client_email(
    connection: mysql.connector.MySQLConnection,
    email: str,
    client_id: str | None = None,
) -> None:
    cursor = connection.cursor()
    try:
        query = (
            "SELECT 1 FROM clients "
            "WHERE LOWER(email) = LOWER(%s) AND archived_at IS NULL"
        )
        values: tuple[str, ...] = (email,)
        if client_id is not None:
            query += " AND client_id <> %s"
            values += (client_id,)
        cursor.execute(query, values)
        if cursor.fetchone() is not None:
            raise HTTPException(
                status_code=409,
                detail="An active client already uses this email address.",
            )
    finally:
        cursor.close()


@app.post(
    "/api/clients",
    status_code=status.HTTP_201_CREATED,
)
def create_client(
    payload: ClientInput,
    connection: mysql.connector.MySQLConnection = Depends(get_connection),
) -> dict[str, object]:
    _ensure_unique_client_email(connection, payload.email)
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT client_id FROM clients")
        existing_ids = [{"client_id": row[0]} for row in cursor.fetchall()]
        client_id = next_client_id(existing_ids)
        with _transaction(connection):
            cursor.execute(
                "INSERT INTO clients "
                "(client_id, name, email, is_member, is_pwd, is_student, "
                "is_worker, valid_id_number, created_at, welcome_email_status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')",
                (
                    client_id,
                    payload.name,
                    payload.email,
                    False,
                    payload.is_pwd,
                    payload.is_student,
                    payload.is_worker,
                    payload.valid_id_number,
                    current_timestamp(),
                ),
            )
    finally:
        cursor.close()
    client = get_client(client_id, connection)
    email_result = send_client_welcome_email_once(connection, client)
    client["welcome_email"] = email_result.as_dict()
    return client


@app.put("/api/clients/{client_id}")
def replace_client(
    client_id: str,
    payload: ClientInput,
    connection: mysql.connector.MySQLConnection = Depends(get_connection),
) -> dict[str, object]:
    client_id = client_id.upper()
    _ensure_unique_client_email(connection, payload.email, client_id)
    cursor = connection.cursor()
    try:
        with _transaction(connection):
            cursor.execute(
                "UPDATE clients SET name = %s, email = %s, "
                "is_pwd = %s, is_student = %s, is_worker = %s, "
                "valid_id_number = %s "
                "WHERE client_id = %s AND archived_at IS NULL",
                (
                    payload.name,
                    payload.email,
                    payload.is_pwd,
                    payload.is_student,
                    payload.is_worker,
                    payload.valid_id_number,
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
                    raise HTTPException(status_code=404, detail="Active client not found.")
    finally:
        cursor.close()
    return get_client(client_id, connection)


@app.delete("/api/clients/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
def archive_client(
    client_id: str,
    connection: mysql.connector.MySQLConnection = Depends(get_connection),
) -> Response:
    cursor = connection.cursor()
    try:
        with _transaction(connection):
            cursor.execute(
                "UPDATE clients SET archived_at = %s "
                "WHERE client_id = %s AND archived_at IS NULL",
                (current_timestamp(), client_id.upper()),
            )
            if cursor.rowcount != 1:
                raise HTTPException(status_code=404, detail="Active client not found.")
    finally:
        cursor.close()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/clients/{client_id}/restore")
def restore_client(
    client_id: str,
    connection: mysql.connector.MySQLConnection = Depends(get_connection),
) -> dict[str, object]:
    cursor = connection.cursor()
    try:
        with _transaction(connection):
            cursor.execute(
                "UPDATE clients SET archived_at = NULL "
                "WHERE client_id = %s AND archived_at IS NOT NULL",
                (client_id.upper(),),
            )
            if cursor.rowcount != 1:
                raise HTTPException(status_code=404, detail="Archived client not found.")
    finally:
        cursor.close()
    return get_client(client_id, connection)


def _get_active_client(
    connection: mysql.connector.MySQLConnection,
    client_id: str,
) -> dict[str, object]:
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT client_id, name FROM clients "
            "WHERE client_id = %s AND archived_at IS NULL",
            (client_id.upper(),),
        )
        client = cursor.fetchone()
        if client is None:
            raise HTTPException(status_code=404, detail="Active client not found.")
        return client
    finally:
        cursor.close()


def _ensure_employee_exists(
    connection: mysql.connector.MySQLConnection,
    employee_name: str | None,
) -> None:
    if not employee_name:
        return

    cursor = connection.cursor()
    try:
        cursor.execute("SELECT first_name, last_name FROM employees")
        employees = cursor.fetchall()
    finally:
        cursor.close()

    normalized_name = " ".join(employee_name.split()).casefold()
    if not any(
        " ".join(f"{first_name} {last_name}".split()).casefold() == normalized_name
        for first_name, last_name in employees
    ):
        raise HTTPException(
            status_code=422,
            detail="Performed-by name must match an existing employee profile.",
        )


@overload
def _attendance_records(
    connection: mysql.connector.MySQLConnection,
    attendance_id: None = None,
) -> list[dict[str, object]]: ...


@overload
def _attendance_records(
    connection: mysql.connector.MySQLConnection,
    attendance_id: int,
) -> dict[str, object]: ...


def _attendance_records(
    connection: mysql.connector.MySQLConnection,
    attendance_id: int | None = None,
) -> list[dict[str, object]] | dict[str, object]:
    cursor = connection.cursor(dictionary=True)
    try:
        query = (
            "SELECT attendance.id, attendance.client_id, attendance.client_name, "
            "COALESCE(clients.email, '') AS email, attendance.timestamp "
            "FROM attendance LEFT JOIN clients "
            "ON clients.client_id = attendance.client_id"
        )
        if attendance_id is not None:
            cursor.execute(query + " WHERE attendance.id = %s", (attendance_id,))
            row = cursor.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Attendance record not found.")
            return _serialize(row)
        cursor.execute(query + " ORDER BY attendance.id")
        return [_serialize(row) for row in cursor.fetchall()]
    finally:
        cursor.close()


def _check_attendance_date(
    connection: mysql.connector.MySQLConnection,
    client_id: str,
    timestamp: str,
    exclude_id: int | None = None,
) -> None:
    query = "SELECT 1 FROM attendance WHERE client_id = %s AND timestamp LIKE %s"
    values: tuple[object, ...] = (client_id, f"{timestamp[:10]}%")
    if exclude_id is not None:
        query += " AND id <> %s"
        values += (exclude_id,)
    query += " LIMIT 1"
    cursor = connection.cursor()
    try:
        cursor.execute(query, values)
        if cursor.fetchone() is not None:
            raise HTTPException(
                status_code=409,
                detail="This client already has an attendance record on that date.",
            )
    finally:
        cursor.close()


@app.get("/api/attendance")
def list_attendance(
    connection: mysql.connector.MySQLConnection = Depends(get_connection),
) -> list[dict[str, object]]:
    return _attendance_records(connection)


@app.get("/api/attendance/{attendance_id}")
def get_attendance(
    attendance_id: int,
    connection: mysql.connector.MySQLConnection = Depends(get_connection),
) -> dict[str, object]:
    return _attendance_records(connection, attendance_id)


@app.post(
    "/api/attendance",
    status_code=status.HTTP_201_CREATED,
)
def create_attendance(
    payload: AttendanceInput,
    connection: mysql.connector.MySQLConnection = Depends(get_connection),
) -> dict[str, object]:
    client = _get_active_client(connection, payload.client_id)
    timestamp = payload.timestamp or current_timestamp()
    _check_attendance_date(connection, payload.client_id, timestamp)
    cursor = connection.cursor()
    try:
        with _transaction(connection):
            cursor.execute(
                "INSERT INTO attendance (client_id, client_name, timestamp) "
                "VALUES (%s, %s, %s)",
                (payload.client_id, client["name"], timestamp),
            )
            attendance_id = cursor.lastrowid
    finally:
        cursor.close()
    return _attendance_records(connection, attendance_id)


@app.put("/api/attendance/{attendance_id}")
def replace_attendance(
    attendance_id: int,
    payload: AttendanceReplace,
    connection: mysql.connector.MySQLConnection = Depends(get_connection),
) -> dict[str, object]:
    client = _get_active_client(connection, payload.client_id)
    _check_attendance_date(
        connection,
        payload.client_id,
        payload.timestamp,
        attendance_id,
    )
    cursor = connection.cursor()
    try:
        with _transaction(connection):
            cursor.execute(
                "UPDATE attendance SET client_id = %s, client_name = %s, "
                "timestamp = %s WHERE id = %s",
                (
                    payload.client_id,
                    client["name"],
                    payload.timestamp,
                    attendance_id,
                ),
            )
            if cursor.rowcount == 0:
                cursor.execute(
                    "SELECT 1 FROM attendance WHERE id = %s",
                    (attendance_id,),
                )
                if cursor.fetchone() is None:
                    raise HTTPException(status_code=404, detail="Attendance record not found.")
    finally:
        cursor.close()
    return _attendance_records(connection, attendance_id)


@app.delete(
    "/api/attendance/{attendance_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_attendance(
    attendance_id: int,
    connection: mysql.connector.MySQLConnection = Depends(get_connection),
) -> Response:
    cursor = connection.cursor()
    try:
        with _transaction(connection):
            cursor.execute("DELETE FROM attendance WHERE id = %s", (attendance_id,))
            if cursor.rowcount != 1:
                raise HTTPException(status_code=404, detail="Attendance record not found.")
    finally:
        cursor.close()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@overload
def _payment_records(
    connection: mysql.connector.MySQLConnection,
    payment_id: None = None,
) -> list[dict[str, object]]: ...


@overload
def _payment_records(
    connection: mysql.connector.MySQLConnection,
    payment_id: int,
) -> dict[str, object]: ...
 

def _payment_records(
    connection: mysql.connector.MySQLConnection,
    payment_id: int | None = None,
) -> list[dict[str, object]] | dict[str, object]:
    cursor = connection.cursor(dictionary=True)
    try:
        query = (
            "SELECT id, client_id, client_name, amount, description, timestamp, "
            "assisting_employee "
            "FROM payments"
        )
        if payment_id is not None:
            cursor.execute(query + " WHERE id = %s", (payment_id,))
            row = cursor.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Payment record not found.")
            return _serialize(row)
        cursor.execute(query + " ORDER BY id")
        return [_serialize(row) for row in cursor.fetchall()]
    finally:
        cursor.close()


def _refresh_client_membership(
    cursor: mysql.connector.cursor.MySQLCursor,
    client_id: str,
) -> None:
    cursor.execute(
        "UPDATE clients SET is_member = EXISTS ("
        "SELECT 1 FROM payments "
        "WHERE payments.client_id = clients.client_id "
        "AND LOWER(payments.description) = 'gym membership') "
        "WHERE client_id = %s",
        (client_id,),
    )


@app.get("/api/payments")
def list_payments(
    connection: mysql.connector.MySQLConnection = Depends(get_connection),
) -> list[dict[str, object]]:
    return _payment_records(connection)


@app.get("/api/payments/{payment_id}")
def get_payment(
    payment_id: int,
    connection: mysql.connector.MySQLConnection = Depends(get_connection),
) -> dict[str, object]:
    return _payment_records(connection, payment_id)


@app.post(
    "/api/payments",
    status_code=status.HTTP_201_CREATED,
)
def create_payment(
    payload: PaymentInput,
    connection: mysql.connector.MySQLConnection = Depends(get_connection),
) -> dict[str, object]:
    client = _get_active_client(connection, payload.client_id)
    cursor = connection.cursor()
    try:
        with _transaction(connection):
            cursor.execute(
                "INSERT INTO payments "
                "(client_id, client_name, amount, description, timestamp) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    payload.client_id,
                    client["name"],
                    payload.amount,
                    payload.description,
                    current_timestamp(),
                ),
            )
            payment_id = cursor.lastrowid
            _refresh_client_membership(cursor, payload.client_id)
    finally:
        cursor.close()
    return _payment_records(connection, payment_id)


@app.put("/api/payments/{payment_id}")
def replace_payment(
    payment_id: int,
    payload: PaymentInput,
    connection: mysql.connector.MySQLConnection = Depends(get_connection),
) -> dict[str, object]:
    client = _get_active_client(connection, payload.client_id)
    cursor = connection.cursor()
    try:
        with _transaction(connection):
            cursor.execute(
                "SELECT client_id FROM payments WHERE id = %s",
                (payment_id,),
            )
            previous_payment = cursor.fetchone()
            if previous_payment is None:
                raise HTTPException(
                    status_code=404, detail="Payment record not found."
                )
            cursor.execute(
                "UPDATE payments SET client_id = %s, client_name = %s, "
                "amount = %s, description = %s WHERE id = %s",
                (
                    payload.client_id,
                    client["name"],
                    payload.amount,
                    payload.description,
                    payment_id,
                ),
            )
            _refresh_client_membership(cursor, previous_payment[0])
            if payload.client_id != previous_payment[0]:
                _refresh_client_membership(cursor, payload.client_id)
    finally:
        cursor.close()
    return _payment_records(connection, payment_id)


@app.delete("/api/payments/{payment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_payment(
    payment_id: int,
    connection: mysql.connector.MySQLConnection = Depends(get_connection),
) -> Response:
    cursor = connection.cursor()
    try:
        with _transaction(connection):
            cursor.execute(
                "SELECT client_id FROM payments WHERE id = %s",
                (payment_id,),
            )
            payment = cursor.fetchone()
            if payment is None:
                raise HTTPException(
                    status_code=404, detail="Payment record not found."
                )
            cursor.execute("DELETE FROM payments WHERE id = %s", (payment_id,))
            _refresh_client_membership(cursor, payment[0])
    finally:
        cursor.close()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@overload
def _maintenance_records(
    connection: mysql.connector.MySQLConnection,
    record_id: None = None,
) -> list[dict[str, object]]: ...


@overload
def _maintenance_records(
    connection: mysql.connector.MySQLConnection,
    record_id: int,
) -> dict[str, object]: ...


def _maintenance_records(
    connection: mysql.connector.MySQLConnection,
    record_id: int | None = None,
) -> list[dict[str, object]] | dict[str, object]:
    cursor = connection.cursor(dictionary=True)
    try:
        query = (
            "SELECT id, machine, description, cost, timestamp, performed_by "
            "FROM maintenance"
        )
        if record_id is not None:
            cursor.execute(query + " WHERE id = %s", (record_id,))
            row = cursor.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Maintenance record not found.")
            return _serialize(row)
        cursor.execute(query + " ORDER BY id")
        return [_serialize(row) for row in cursor.fetchall()]
    finally:
        cursor.close()


@app.get("/api/maintenance")
def list_maintenance(
    connection: mysql.connector.MySQLConnection = Depends(get_connection),
) -> list[dict[str, object]]:
    return _maintenance_records(connection)


@app.get("/api/maintenance/{record_id}")
def get_maintenance(
    record_id: int,
    connection: mysql.connector.MySQLConnection = Depends(get_connection),
) -> dict[str, object]:
    return _maintenance_records(connection, record_id)


@app.post(
    "/api/maintenance",
    status_code=status.HTTP_201_CREATED,
)
def create_maintenance(
    payload: MaintenanceInput,
    connection: mysql.connector.MySQLConnection = Depends(get_connection),
) -> dict[str, object]:
    _ensure_employee_exists(connection, payload.performed_by)
    cursor = connection.cursor()
    try:
        with _transaction(connection):
            cursor.execute(
                "INSERT INTO maintenance "
                "(machine, description, cost, timestamp, performed_by) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    payload.machine,
                    payload.description,
                    payload.cost,
                    current_timestamp(),
                    payload.performed_by or "",
                ),
            )
            record_id = cursor.lastrowid
    finally:
        cursor.close()
    return _maintenance_records(connection, record_id)


@app.put("/api/maintenance/{record_id}")
def replace_maintenance(
    record_id: int,
    payload: MaintenanceInput,
    connection: mysql.connector.MySQLConnection = Depends(get_connection),
) -> dict[str, object]:
    _ensure_employee_exists(connection, payload.performed_by)
    cursor = connection.cursor()
    try:
        with _transaction(connection):
            cursor.execute(
                "UPDATE maintenance SET machine = %s, description = %s, "
                "cost = %s, performed_by = COALESCE(%s, performed_by) "
                "WHERE id = %s",
                (
                    payload.machine,
                    payload.description,
                    payload.cost,
                    payload.performed_by,
                    record_id,
                ),
            )
            if cursor.rowcount == 0:
                cursor.execute(
                    "SELECT 1 FROM maintenance WHERE id = %s",
                    (record_id,),
                )
                if cursor.fetchone() is None:
                    raise HTTPException(
                        status_code=404,
                        detail="Maintenance record not found.",
                    )
    finally:
        cursor.close()
    return _maintenance_records(connection, record_id)


@app.delete(
    "/api/maintenance/{record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_maintenance(
    record_id: int,
    connection: mysql.connector.MySQLConnection = Depends(get_connection),
) -> Response:
    cursor = connection.cursor()
    try:
        with _transaction(connection):
            cursor.execute("DELETE FROM maintenance WHERE id = %s", (record_id,))
            if cursor.rowcount != 1:
                raise HTTPException(status_code=404, detail="Maintenance record not found.")
    finally:
        cursor.close()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
