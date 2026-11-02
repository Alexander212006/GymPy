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

The MySQL connection settings are in `database/connection.py`, and the table
definitions are in `database/schema.sql`. GymPy creates the tables on startup
and stores all records directly in MySQL.

On the first startup, GymPy prompts you to enter and confirm a shared login
password. It stores only a salted PBKDF2 hash in the `app_credentials` table
and logs you in after setup. Run the program in a terminal so the hidden
password prompts can receive input.
