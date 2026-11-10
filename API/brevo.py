from dataclasses import dataclass
import html
import json
import logging
import os
from pathlib import Path
import re
from typing import Literal, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, uuid5

import mysql.connector
from dotenv import dotenv_values

from app.common import current_timestamp
from database.queries import (
    claim_client_welcome_email,
    mark_client_welcome_email_failed,
    mark_client_welcome_email_sent,
)


BREVO_EMAIL_URL = "https://api.brevo.com/v3/smtp/email"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ENV_FILE = PROJECT_ROOT / ".env"
BREVO_ENV_NAMES = (
    "BREVO_API_KEY",
    "BREVO_SENDER_EMAIL",
    "BREVO_SENDER_NAME",
)
LOGGER = logging.getLogger(__name__)
_BREVO_KEY_PATTERN = re.compile(r"\bxkeysib-[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_LABELED_KEY_PATTERN = re.compile(
    r"(?i)(api[-_ ]?key\s*[:=]\s*)[^\s,;]+"
)
_MAX_PROVIDER_ERROR_LENGTH = 300


def _load_brevo_environment() -> None:
    """Load only Brevo settings from the project-root .env file."""
    if not PROJECT_ENV_FILE.is_file():
        return
    try:
        project_values = dotenv_values(PROJECT_ENV_FILE, encoding="utf-8")
    except (OSError, UnicodeError) as error:
        LOGGER.warning(
            "Could not read Brevo settings from %s: %s",
            PROJECT_ENV_FILE,
            error,
        )
        return
    for name in BREVO_ENV_NAMES:
        value = project_values.get(name)
        if value is not None:
            # The requested project .env is authoritative for Brevo settings,
            # while unrelated inherited settings (for example MySQL) stay put.
            os.environ[name] = str(value)


_load_brevo_environment()


@dataclass(frozen=True)
class WelcomeEmailResult:
    status: Literal["sent", "failed", "skipped"]
    message: str
    message_id: str | None = None

    def as_dict(self) -> dict[str, str]:
        result = {"status": self.status, "message": self.message}
        if self.message_id:
            result["message_id"] = self.message_id
        return result


def _client_text(client: Mapping[str, object], field: str) -> str:
    return str(client[field]).strip()


def _welcome_email_idempotency_key(client: Mapping[str, object]) -> str:
    """Return the same provider idempotency key for the same registration."""
    identity = "|".join(
        (
            _client_text(client, "client_id"),
            str(client.get("created_at", "")).strip(),
            _client_text(client, "email").casefold(),
        )
    )
    return str(uuid5(NAMESPACE_URL, f"https://gympy.local/welcome/{identity}"))


def _safe_provider_text(value: object, api_key: str) -> str:
    text = " ".join(str(value).split())
    if api_key:
        text = text.replace(api_key, "[REDACTED]")
    text = _BREVO_KEY_PATTERN.sub("[REDACTED]", text)
    text = _LABELED_KEY_PATTERN.sub(r"\1[REDACTED]", text)
    return text[:_MAX_PROVIDER_ERROR_LENGTH] or "unknown"


def _brevo_error_details(error: HTTPError, api_key: str) -> tuple[str, str]:
    provider_code: object = "unknown"
    provider_message: object = error.reason or "No response message returned"
    try:
        body = json.loads(error.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        body = None
    if isinstance(body, dict):
        provider_code = body.get("code", provider_code)
        provider_message = body.get("message", provider_message)
    return (
        _safe_provider_text(provider_code, api_key),
        _safe_provider_text(provider_message, api_key),
    )


def send_client_welcome_email(
    client: Mapping[str, object],
) -> str | None:
    """Ask Brevo to send one branded welcome email and return its message ID."""
    api_key = os.getenv("BREVO_API_KEY", "").strip()
    sender_email = os.getenv("BREVO_SENDER_EMAIL", "").strip()
    sender_name = os.getenv("BREVO_SENDER_NAME", "GymPy").strip() or "GymPy"
    missing_settings = [
        name
        for name, value in (
            ("BREVO_API_KEY", api_key),
            ("BREVO_SENDER_EMAIL", sender_email),
        )
        if not value
    ]
    if missing_settings:
        missing_list = ", ".join(missing_settings)
        LOGGER.warning(
            "Brevo welcome email is not configured; missing %s in %s.",
            missing_list,
            PROJECT_ENV_FILE,
        )
        raise RuntimeError(
            f"Missing Brevo configuration in project .env: {missing_list}."
        )

    raw_name = _client_text(client, "name")
    raw_email = _client_text(client, "email")
    raw_client_id = _client_text(client, "client_id")
    name = html.escape(raw_name)
    email = html.escape(raw_email)
    client_id = html.escape(raw_client_id)
    email_name = " ".join(raw_name.splitlines())

    html_content = f"""\
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Welcome to GymPy</title>
  </head>
  <body style="margin:0;background:#edf3f0;font-family:Arial,Helvetica,sans-serif;color:#17251f;">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;">Your GymPy client profile is ready.</div>
    <div style="max-width:620px;margin:0 auto;padding:32px 16px;">
      <div style="overflow:hidden;border-radius:18px;background:#ffffff;box-shadow:0 10px 30px rgba(15,61,46,.14);">
        <div style="padding:36px 28px;background:#0f3d2e;color:#ffffff;text-align:center;">
          <div style="font-size:15px;letter-spacing:5px;font-weight:700;">GYMPY</div>
          <h1 style="margin:18px 0 10px;font-size:28px;line-height:1.25;">Welcome to GymPy, {name}!</h1>
          <p style="margin:0;color:#d7eee5;font-size:17px;line-height:1.5;">Your fitness journey starts here.</p>
        </div>
        <div style="padding:34px 30px;">
          <p style="margin:0 0 22px;font-size:16px;line-height:1.65;">We are excited to welcome you to the GymPy community. Your profile is ready, and our team looks forward to supporting you as you build stronger, healthier habits.</p>
          <div style="padding:22px;border:1px solid #cfe3da;border-radius:12px;background:#f1f8f5;text-align:center;">
            <div style="font-size:12px;color:#587067;letter-spacing:1.4px;text-transform:uppercase;">Your Client ID</div>
            <div style="margin-top:8px;color:#0f3d2e;font-size:30px;font-weight:700;">{client_id}</div>
          </div>
          <div style="margin-top:24px;padding-top:20px;border-top:1px solid #e1e9e5;">
            <div style="font-size:12px;color:#687b73;letter-spacing:.8px;text-transform:uppercase;">Registered email address</div>
            <div style="margin-top:7px;font-size:15px;word-break:break-word;">{email}</div>
          </div>
          <p style="margin:24px 0 0;color:#687b73;font-size:13px;line-height:1.6;">Keep your client ID handy when visiting the gym. For your privacy, this email does not include your student or PWD ID number.</p>
        </div>
        <div style="padding:19px;background:#e4f0eb;color:#466158;text-align:center;font-size:12px;line-height:1.5;">We look forward to seeing you at GymPy.</div>
      </div>
    </div>
  </body>
</html>
"""
    text_content = (
        f"Welcome to GymPy, {raw_name}!\n\n"
        "Your fitness journey starts here.\n\n"
        "We are excited to welcome you to the GymPy community. Your client "
        "profile is ready, and our team looks forward to supporting you.\n\n"
        f"Client ID: {raw_client_id}\n"
        f"Registered email address: {raw_email}\n\n"
        "We look forward to seeing you at GymPy."
    )
    payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": raw_email, "name": email_name}],
        "subject": f"Welcome to GymPy, {email_name}!",
        "htmlContent": html_content,
        "textContent": text_content,
        "headers": {
            "IdempotencyKey": _welcome_email_idempotency_key(client),
        },
    }
    request = Request(
        BREVO_EMAIL_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "accept": "application/json",
            "api-key": api_key,
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError(
                    f"Brevo returned unexpected HTTP status {response.status}."
                )
            response_body = response.read()
    except HTTPError as error:
        provider_code, provider_message = _brevo_error_details(error, api_key)
        if error.code == 400 and provider_code == "duplicate_parameter":
            return None
        LOGGER.warning(
            "Brevo request failed: HTTP %s; code=%s; message=%s",
            error.code,
            provider_code,
            provider_message,
        )
        credential_hint = ""
        if error.code == 401:
            credential_hint = (
                " Check the API key status, expiry, and Brevo authorized-IP "
                "settings. If you change project .env, restart GymPy."
            )
        elif error.code == 403:
            credential_hint = (
                " Check the API key's Transactional email permission and the "
                "Brevo sender authorization."
            )
        raise RuntimeError(
            "Brevo rejected the welcome email "
            f"(HTTP {error.code}; code={provider_code}; "
            f"message={provider_message}).{credential_hint}"
        ) from error
    except (OSError, URLError, TimeoutError) as error:
        raise RuntimeError(f"Could not connect to Brevo: {error}") from error

    try:
        response_data = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(response_data, dict):
        return None
    message_id = response_data.get("messageId")
    return str(message_id) if message_id else None


def send_client_welcome_email_once(
    connection: mysql.connector.MySQLConnection,
    client: Mapping[str, object],
) -> WelcomeEmailResult:
    """Claim, send, and record a welcome email without affecting the profile."""
    client_id = _client_text(client, "client_id")
    try:
        claimed = claim_client_welcome_email(
            connection,
            client_id,
            current_timestamp(),
        )
    except mysql.connector.Error:
        return WelcomeEmailResult(
            "failed",
            "Client profile was saved, but GymPy could not reserve the welcome "
            "email delivery in MySQL. No email was sent.",
        )

    if not claimed:
        return WelcomeEmailResult(
            "skipped",
            "Welcome email was already attempted; no duplicate was sent.",
        )

    try:
        message_id = send_client_welcome_email(client)
    except RuntimeError as error:
        try:
            mark_client_welcome_email_failed(connection, client_id)
        except mysql.connector.Error:
            pass
        return WelcomeEmailResult(
            "failed",
            f"Client profile was saved, but the welcome email could not be sent: {error}",
        )
    except Exception:
        # Email is a non-critical side effect. Keep unexpected transport or
        # formatting failures from taking down either registration path.
        try:
            mark_client_welcome_email_failed(connection, client_id)
        except mysql.connector.Error:
            pass
        return WelcomeEmailResult(
            "failed",
            "Client profile was saved, but an unexpected welcome email error occurred.",
        )

    try:
        receipt_saved = mark_client_welcome_email_sent(
            connection,
            client_id,
            current_timestamp(),
            message_id,
        )
    except mysql.connector.Error:
        return WelcomeEmailResult(
            "sent",
            "Brevo accepted the welcome email for delivery, but GymPy could not "
            "save the delivery receipt. It will not retry automatically, which "
            "prevents a duplicate email.",
            message_id,
        )

    if not receipt_saved:
        return WelcomeEmailResult(
            "sent",
            "Brevo accepted the welcome email for delivery, but GymPy could not "
            "save the delivery receipt. It will not retry automatically, which "
            "prevents a duplicate email.",
            message_id,
        )

    return WelcomeEmailResult(
        "sent",
        "Welcome email accepted by Brevo for delivery.",
        message_id,
    )
