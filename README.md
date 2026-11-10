# GymPy

## MySQL setup

Install the Python dependency:

```powershell
python -m pip install -r requirements.txt
```

Create the database in MySQL:

```sql
CREATE DATABASE gympy;
```

GymPy reads its MySQL connection settings from the project `.env` file:

```dotenv
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=
MYSQL_DATABASE=gympy
```

Edit these values in `.env` to match your local MySQL setup. The `.env` file
is ignored by Git and should not be committed.

The MySQL connection settings are in `database/connection.py`, SQL queries are
in `database/queries.py`, and table definitions are in
`database/schema.sql`. GymPy creates the tables on startup and stores all
records directly in MySQL.

Application code is split by responsibility under `app/`: `main.py` starts the
program, `menus.py` handles navigation, and `clients.py`, `attendance.py`,
`employees.py`, `payments.py`, and `maintenance.py` contain their respective
workflows.
Shared prompts, formatting, and service constants are in `common.py`;
authentication is in `auth.py`.

On the first startup, GymPy prompts you to enter and confirm a shared login
password. It stores only a salted PBKDF2 hash in the `app_credentials` table
and logs you in after setup. Run the program in a terminal so the hidden
password prompts can receive input.

Start GymPy from the project root using either command:

```powershell
python -m app.main
python app\main.py
```

## HTTP API

GymPy also provides a REST API for client, attendance, payment, and
maintenance records. Install the dependencies above and create the MySQL
database. Start the API from the project root:

```powershell
python -m uvicorn API.main:app --host 127.0.0.1 --port 8000
```

The API does not require authentication. Anyone who can reach the server can
read, create, update, archive, restore, or delete records. Keep it bound to
localhost for local development; do not expose it to an untrusted network.
Interactive API documentation is available at
`http://127.0.0.1:8000/docs`.

Each resource supports `GET` on its collection and item, `POST` to create,
`PUT` to replace an item, and `DELETE` to delete it. Resources and item
identifiers are:

| Resource | Collection | Item identifier |
| --- | --- | --- |
| Clients | `/api/clients` | Client ID, e.g. `C0001` |
| Attendance | `/api/attendance` | Attendance record ID |
| Payments | `/api/payments` | Payment record ID |
| Maintenance | `/api/maintenance` | Maintenance record ID |

For example, create a client and list active clients in PowerShell:

```powershell
curl.exe -u gympy:YOUR_GYMPY_PASSWORD `
  -H "Content-Type: application/json" `
  -d '{"name":"Alex Lee","email":"alex@example.com","is_student":true}' `
  http://127.0.0.1:8000/api/clients

curl.exe -u gympy:YOUR_GYMPY_PASSWORD http://127.0.0.1:8000/api/clients
```

`PUT` requests require the complete writable record body. `POST` returns the
created record with HTTP 201, successful `DELETE` returns HTTP 204, invalid
input returns HTTP 422, and missing records return HTTP 404. Deleting a client
archives it to preserve attendance and payment history; archived clients can
be listed using `GET /api/clients?include_archived=true` and restored with
`POST /api/clients/{client_id}/restore`. Attendance can only be recorded for
active clients, and the API enforces the one-attendance-per-client-per-day rule.
API responses include record IDs for attendance, payments, and maintenance;
amounts and costs are returned as decimal strings. Client responses include
`is_member` as a Boolean, updated from Gym Membership payment records.

## Brevo welcome emails

After a new client profile is committed to MySQL, both the terminal application
and `POST /api/clients` automatically request a welcome email through Brevo's
transactional email API. Create a Brevo API key, verify the sender address (or
its domain) in Brevo, and add these values to the project `.env` file:

```dotenv
BREVO_API_KEY=your-brevo-api-key
BREVO_SENDER_EMAIL=verified-sender@example.com
BREVO_SENDER_NAME=GymPy
```

Install dependencies with `python -m pip install -r requirements.txt` if
needed. Use a Brevo **API key**, not an SMTP key. The Brevo integration loads
its settings directly from the project-root `.env` on startup, and `.env` is
excluded from Git so the API key is not committed. Keep real credentials out
of `.env.example`, source control, screenshots, and logs.

The branded dark-green message includes the client's name, client ID, and
registered email; it never includes the stored student/PWD ID number. The
plain-text fallback contains the same essential details.

The API returns the saved client with a `welcome_email` object. Its `status` is
`sent` when Brevo accepted the message, `failed` when the request could not be
sent, or `skipped` when an attempt was already recorded. The terminal displays
the equivalent message. A failure never removes or rolls back the saved client.

GymPy atomically records each welcome-email attempt in MySQL and also sends a
stable Brevo idempotency key. It does not automatically retry a failed or
uncertain attempt, preventing repeated requests, process restarts, or accidental
retries from sending duplicate welcome messages.

### Test a welcome email

1. Put valid Brevo settings in `.env` and use an inbox you can access for the
   new client's email address.
2. Start either `python -m app.main` and add a client, or start the API and send
   a `POST /api/clients` request with a new email address.
3. Confirm the terminal message or the API response reports `sent`. This means
   Brevo accepted the message for delivery.
4. Check the recipient inbox and Brevo's transactional email logs. Repeating
   the same registration does not send another welcome email.

Run the mocked automated checks without contacting Brevo or MySQL:

```powershell
python -m unittest discover -s tests -v
```

### Troubleshoot welcome email delivery

- `Set BREVO_API_KEY...` means one or both required `.env` values are missing.
- HTTP 401 means Brevo rejected authentication. Read the accompanying provider
  message: besides an invalid or expired key, Brevo may reject a request from
  an unrecognized public IP until that IP is added under Brevo's authorized-IP
  security settings. HTTP 403 indicates insufficient key permissions, and HTTP
  429 indicates a Brevo rate or plan limit.
- A connection error points to DNS, firewall, proxy, or general network access.
- If GymPy reports that Brevo accepted the message but it does not arrive,
  inspect Brevo's transactional logs, the recipient's spam folder, suppression
  status, and the sender domain's SPF/DKIM configuration.
- Inspect `welcome_email_status`, `welcome_email_attempted_at`,
  `welcome_email_sent_at`, and `welcome_email_message_id` on the client's MySQL
  row when diagnosing an attempt. Never print or log `BREVO_API_KEY`.

The **Client records** main-menu option opens a submenu to view and update
active clients, archive a client, restore a client, and view archived profiles.
Archived clients are hidden from active client lists and attendance/payment
selection, while their historical records remain in the database.

New client profiles require a valid email address. During profile creation,
GymPy asks whether the client is a PWD, a student, or a worker, and requests a
valid ID number if the client is a PWD or student. The valid ID number is
stored on the client profile, shown in active and archived client tables, and
required for PWD/student clients submitted through the API. Client records can
be searched by ID, name, or email from the Client Records menu.
Existing databases receive missing client profile columns automatically on
startup. The migration replaces the old client `membership` text column with
the `is_member` Boolean, setting it from Gym Membership payment history, and
permanently deletes the old client contact column and its stored values.

Service payments use the rates displayed in the services menu. The payment
form accepts only an employee name matching a profile in the database and
records that employee as assisting with the payment. Member rates apply after a
Gym membership payment has been recorded; each client can
purchase Gym membership only once. Full month, half month, and daily sessions
remain valid for 30, 15, and 1 day respectively. Clients cannot purchase any
additional service while one of these sessions is still valid. GymPy displays
the calculated amount and asks for confirmation before recording a payment.

The main menu's **Attendance records** option displays logged attendance
entries; **Log client attendance** remains a separate option for recording a
new visit. **View active sessions** lists each client's current session along
with its purchase and expiration times.

The **Machine maintenance record** option displays a maintenance history table
with record IDs and the date each machine was last serviced, then lets staff
add or edit a record, or return to the main menu. New and edited records
require the name of an employee profile already in the database, and show who
performed the maintenance.

The **Add employee profile** option saves an employee's first and last name,
contact number, address, sex, and age to the `employees` table. Employee
contact numbers must be 11 digits and start with `09`; age must be from 18 to
50.
