import json
import os
from contextlib import redirect_stdout
from io import BytesIO, StringIO
import unittest
from unittest.mock import Mock, call, patch
from urllib.error import HTTPError
from uuid import UUID

import mysql.connector

from API import brevo
from API import main as api_main
from app import clients as terminal_clients


CLIENT = {
    "client_id": "C0042",
    "name": "Sam <Strong> & Co.",
    "email": "sam+gym@example.com",
    "created_at": "2026-11-10T09:15:00+08:00",
}


class FakeResponse:
    status = 201

    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class FakeCursor:
    def __init__(self) -> None:
        self.closed = False
        self.executions = []

    def execute(self, statement, values=None) -> None:
        self.executions.append((statement, values))

    def fetchall(self):
        return []

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    def __init__(self) -> None:
        self.committed = False
        self.commit_count = 0
        self.rollback_count = 0
        self.test_cursor = FakeCursor()

    def cursor(self):
        return self.test_cursor

    def commit(self) -> None:
        self.committed = True
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1


class BrevoTransportTests(unittest.TestCase):
    def test_payload_is_branded_escaped_and_idempotent(self) -> None:
        requests = []

        def fake_urlopen(request, *, timeout):
            requests.append((request, timeout))
            return FakeResponse(b'{"messageId":"brevo-message-42"}')

        environment = {
            "BREVO_API_KEY": "test-api-key",
            "BREVO_SENDER_EMAIL": "verified@gympy.example",
            "BREVO_SENDER_NAME": "GymPy",
        }
        with patch.dict(os.environ, environment, clear=True), patch(
            "API.brevo.urlopen", side_effect=fake_urlopen
        ):
            first_message_id = brevo.send_client_welcome_email(CLIENT)
            second_message_id = brevo.send_client_welcome_email(CLIENT)

        self.assertEqual(first_message_id, "brevo-message-42")
        self.assertEqual(second_message_id, "brevo-message-42")
        self.assertEqual(len(requests), 2)
        self.assertEqual([timeout for _, timeout in requests], [15, 15])
        for request, _ in requests:
            self.assertEqual(request.full_url, brevo.BREVO_EMAIL_URL)
            self.assertEqual(request.headers["Api-key"], environment["BREVO_API_KEY"])

        payloads = [json.loads(request.data.decode("utf-8")) for request, _ in requests]
        payload = payloads[0]
        self.assertEqual(payload["sender"]["email"], "verified@gympy.example")
        self.assertEqual(payload["to"], [{"email": CLIENT["email"], "name": CLIENT["name"]}])
        self.assertEqual(payload["subject"], "Welcome to GymPy, Sam <Strong> & Co.!")
        self.assertIn("Welcome to GymPy, Sam &lt;Strong&gt; &amp; Co.!", payload["htmlContent"])
        self.assertNotIn("Sam <Strong> & Co.", payload["htmlContent"])
        self.assertIn("Your fitness journey starts here.", payload["htmlContent"])
        self.assertIn("C0042", payload["htmlContent"])
        self.assertIn("sam+gym@example.com", payload["htmlContent"])
        self.assertIn("Client ID: C0042", payload["textContent"])
        self.assertNotIn("test-api-key", json.dumps(payload))

        first_key = payloads[0]["headers"]["IdempotencyKey"]
        second_key = payloads[1]["headers"]["IdempotencyKey"]
        self.assertEqual(first_key, second_key)
        self.assertEqual(UUID(first_key).version, 5)

    def test_missing_configuration_fails_before_network_access(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch(
            "API.brevo.urlopen"
        ) as mocked_urlopen, self.assertLogs("API.brevo", level="WARNING") as logs:
            with self.assertRaisesRegex(RuntimeError, "BREVO_API_KEY"):
                brevo.send_client_welcome_email(CLIENT)

        mocked_urlopen.assert_not_called()
        self.assertIn("missing BREVO_API_KEY", " ".join(logs.output))

    def test_project_env_is_authoritative_for_brevo_settings_only(self) -> None:
        env_file = Mock()
        env_file.is_file.return_value = True
        project_values = {
            "BREVO_API_KEY": "xkeysib-project-file-test-key",
            "BREVO_SENDER_EMAIL": "sender@example.com",
            "BREVO_SENDER_NAME": "GymPy",
            "MYSQL_PASSWORD": "must-not-be-loaded",
        }
        environment = {
            "BREVO_API_KEY": "xkeysib-stale-process-key",
            "MYSQL_PASSWORD": "keep-existing-mysql-password",
        }
        with patch.object(brevo, "PROJECT_ENV_FILE", env_file), patch(
            "API.brevo.dotenv_values",
            return_value=project_values,
        ) as read_env, patch.dict(os.environ, environment, clear=True):
            brevo._load_brevo_environment()

            self.assertEqual(
                os.environ["BREVO_API_KEY"],
                "xkeysib-project-file-test-key",
            )
            self.assertEqual(
                os.environ["BREVO_SENDER_EMAIL"],
                "sender@example.com",
            )
            self.assertEqual(
                os.environ["MYSQL_PASSWORD"],
                "keep-existing-mysql-password",
            )
        read_env.assert_called_once_with(env_file, encoding="utf-8")

    def test_unauthorized_error_logs_provider_details_without_secret(self) -> None:
        api_key = "xkeysib-super-secret-test-token"
        error_body = json.dumps(
            {
                "code": "unauthorized",
                "message": f"API key: {api_key} is invalid or expired",
            }
        ).encode("utf-8")
        http_error = HTTPError(
            brevo.BREVO_EMAIL_URL,
            401,
            "Unauthorized",
            {},
            BytesIO(error_body),
        )
        environment = {
            "BREVO_API_KEY": api_key,
            "BREVO_SENDER_EMAIL": "verified@gympy.example",
            "BREVO_SENDER_NAME": "GymPy",
        }

        with patch.dict(os.environ, environment, clear=True), patch(
            "API.brevo.urlopen",
            side_effect=http_error,
        ), self.assertLogs("API.brevo", level="WARNING") as logs:
            with self.assertRaises(RuntimeError) as raised:
                brevo.send_client_welcome_email(CLIENT)

        safe_output = f"{raised.exception} {' '.join(logs.output)}"
        self.assertIn("HTTP 401", safe_output)
        self.assertIn("code=unauthorized", safe_output)
        self.assertIn("invalid or expired", safe_output)
        self.assertIn("[REDACTED]", safe_output)
        self.assertNotIn(api_key, safe_output)


class WelcomeEmailWorkflowTests(unittest.TestCase):
    def test_second_attempt_is_skipped_and_transport_runs_once(self) -> None:
        connection = Mock()
        with patch(
            "API.brevo.claim_client_welcome_email", side_effect=[True, False]
        ) as claim_email, patch(
            "API.brevo.send_client_welcome_email",
            return_value="brevo-message-42",
        ) as send_email, patch(
            "API.brevo.mark_client_welcome_email_sent"
        ) as mark_sent, patch(
            "API.brevo.mark_client_welcome_email_failed"
        ) as mark_failed, patch(
            "API.brevo.current_timestamp",
            side_effect=["attempted-at", "sent-at", "second-attempt-at"],
        ):
            first = brevo.send_client_welcome_email_once(connection, CLIENT)
            second = brevo.send_client_welcome_email_once(connection, CLIENT)

        self.assertEqual(first.status, "sent")
        self.assertEqual(first.message_id, "brevo-message-42")
        self.assertEqual(second.status, "skipped")
        self.assertIn("no duplicate", second.message)
        self.assertEqual(
            claim_email.call_args_list,
            [
                call(connection, "C0042", "attempted-at"),
                call(connection, "C0042", "second-attempt-at"),
            ],
        )
        send_email.assert_called_once_with(CLIENT)
        mark_sent.assert_called_once_with(
            connection,
            "C0042",
            "sent-at",
            "brevo-message-42",
        )
        mark_failed.assert_not_called()

    def test_transport_failure_is_nonfatal_and_recorded(self) -> None:
        connection = Mock()
        with patch(
            "API.brevo.claim_client_welcome_email", return_value=True
        ), patch(
            "API.brevo.send_client_welcome_email",
            side_effect=RuntimeError("Brevo rejected the welcome email (HTTP 401)."),
        ), patch(
            "API.brevo.mark_client_welcome_email_failed"
        ) as mark_failed, patch(
            "API.brevo.mark_client_welcome_email_sent"
        ) as mark_sent, patch(
            "API.brevo.current_timestamp", return_value="attempted-at"
        ):
            result = brevo.send_client_welcome_email_once(connection, CLIENT)

        self.assertEqual(result.status, "failed")
        self.assertIn("Client profile was saved", result.message)
        self.assertIn("HTTP 401", result.message)
        mark_failed.assert_called_once_with(connection, "C0042")
        mark_sent.assert_not_called()

    def test_database_claim_failure_does_not_call_brevo(self) -> None:
        connection = Mock()
        with patch(
            "API.brevo.claim_client_welcome_email",
            side_effect=mysql.connector.Error("database unavailable"),
        ), patch(
            "API.brevo.send_client_welcome_email"
        ) as send_email, patch(
            "API.brevo.current_timestamp", return_value="attempted-at"
        ):
            result = brevo.send_client_welcome_email_once(connection, CLIENT)

        self.assertEqual(result.status, "failed")
        self.assertIn("No email was sent", result.message)
        send_email.assert_not_called()


class RegistrationIntegrationTests(unittest.TestCase):
    def test_api_commits_before_email_and_returns_nonfatal_failure(self) -> None:
        connection = FakeConnection()
        created_client = {
            "client_id": "C0042",
            "name": "Sam Example",
            "email": "sam@example.com",
            "is_member": False,
            "is_pwd": False,
            "is_student": False,
            "is_worker": False,
            "valid_id_number": "",
            "created_at": "2026-11-10T09:15:00+08:00",
            "archived_at": None,
        }
        email_failure = brevo.WelcomeEmailResult(
            "failed",
            "Client profile was saved, but the welcome email could not be sent.",
        )

        def send_after_commit(actual_connection, client):
            self.assertIs(actual_connection, connection)
            self.assertTrue(connection.committed)
            self.assertEqual(client, created_client)
            return email_failure

        payload = api_main.ClientInput(
            name="Sam Example",
            email="sam@example.com",
        )
        with patch(
            "API.main._ensure_unique_client_email"
        ) as ensure_unique, patch(
            "API.main.next_client_id", return_value="C0042"
        ), patch(
            "API.main.current_timestamp",
            return_value="2026-11-10T09:15:00+08:00",
        ), patch(
            "API.main.get_client", return_value=created_client.copy()
        ), patch(
            "API.main.send_client_welcome_email_once",
            side_effect=send_after_commit,
        ) as send_email:
            response_data = api_main.create_client(payload, connection)

        ensure_unique.assert_called_once_with(connection, "sam@example.com")
        send_email.assert_called_once()
        self.assertEqual(connection.commit_count, 1)
        self.assertEqual(connection.rollback_count, 0)
        self.assertTrue(connection.test_cursor.closed)
        self.assertEqual(
            response_data["welcome_email"],
            {
                "status": "failed",
                "message": email_failure.message,
            },
        )
        post_route = next(
            route
            for route in api_main.app.routes
            if getattr(route, "path", None) == "/api/clients"
            and "POST" in getattr(route, "methods", set())
        )
        self.assertEqual(post_route.status_code, 201)

    def test_terminal_saves_before_reporting_nonfatal_email_failure(self) -> None:
        connection = Mock()
        data = {"clients": []}
        actions = []
        email_failure = brevo.WelcomeEmailResult(
            "failed",
            "Client profile was saved, but the welcome email could not be sent.",
        )

        def save_record(*_):
            actions.append("saved")

        def send_after_save(actual_connection, client):
            self.assertEqual(actions, ["saved"])
            self.assertIs(actual_connection, connection)
            self.assertEqual(client["email"], "sam@example.com")
            actions.append("email-attempted")
            return email_failure

        output = StringIO()
        with patch("app.clients.show_clients"), patch(
            "app.clients.prompt_required", return_value="Sam Example"
        ), patch(
            "app.clients.prompt_email", return_value="sam@example.com"
        ), patch(
            "app.clients.prompt_yes_no", side_effect=[False, False, False]
        ), patch(
            "app.clients.current_timestamp",
            return_value="2026-11-10T09:15:00+08:00",
        ), patch(
            "app.clients.next_client_id", return_value="C0042"
        ), patch(
            "builtins.input", return_value="y"
        ), patch(
            "app.clients.save_record", side_effect=save_record
        ), patch(
            "app.clients.send_client_welcome_email_once",
            side_effect=send_after_save,
        ), redirect_stdout(output):
            terminal_clients.add_client(data, connection)

        self.assertEqual(actions, ["saved", "email-attempted"])
        self.assertIn("Client profile saved. Client ID: C0042", output.getvalue())
        self.assertIn(email_failure.message, output.getvalue())


if __name__ == "__main__":
    unittest.main()
