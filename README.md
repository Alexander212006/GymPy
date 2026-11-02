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

By default, GymPy connects to `localhost:3306` as `root` with an empty password
and uses the `gympy` database. Set these environment variables to use different
connection details (PowerShell example):

```powershell
$env:MYSQL_HOST = "localhost"
$env:MYSQL_PORT = "3306"
$env:MYSQL_USER = "root"
$env:MYSQL_PASSWORD = "your-password"
$env:MYSQL_DATABASE = "gympy"
```

The MySQL connection settings are in `database/connection.py`, SQL queries are
in `database/queries.py`, and table definitions are in
`database/schema.sql`. GymPy creates the tables on startup and stores all
records directly in MySQL.

On the first startup, GymPy prompts you to enter and confirm a shared login
password. It stores only a salted PBKDF2 hash in the `app_credentials` table
and logs you in after setup. Run the program in a terminal so the hidden
password prompts can receive input.

The **Client records** main-menu option opens a submenu to view and update
active clients, archive a client, restore a client, and view archived profiles.
Archived clients are hidden from active client lists and attendance/payment
selection, while their historical records remain in the database.

New client profiles require an 11-digit phone number starting with `09` and a
valid email address. Existing databases receive the email column automatically
on startup.
