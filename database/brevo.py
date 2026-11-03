import html
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BREVO_EMAIL_URL = "https://api.brevo.com/v3/smtp/email"


def send_client_welcome_email(client: dict[str, str]) -> None:
    api_key = os.getenv("BREVO_API_KEY", "").strip()
    sender_email = os.getenv("BREVO_SENDER_EMAIL", "").strip()
    sender_name = os.getenv("BREVO_SENDER_NAME", "GymPy").strip()
    if not api_key or not sender_email:
        raise RuntimeError(
            "Set BREVO_API_KEY and BREVO_SENDER_EMAIL to send welcome emails."
        )

    name = html.escape(client["name"])
    email = html.escape(client["email"])
    client_id = html.escape(client["client_id"])
    html_content = f"""\
<!doctype html>
<html lang="en">
  <body style="margin:0;background:#f1f5f9;font-family:Arial,sans-serif;color:#172033;">
    <div style="max-width:600px;margin:32px auto;padding:0 16px;">
      <div style="overflow:hidden;border-radius:16px;background:#ffffff;box-shadow:0 8px 28px rgba(15,23,42,.12);">
        <div style="padding:32px;background:#123c35;color:#ffffff;text-align:center;">
          <div style="font-size:14px;letter-spacing:4px;font-weight:bold;">GYMPY</div>
          <h1 style="margin:16px 0 8px;font-size:28px;">Welcome, {name}!</h1>
          <p style="margin:0;color:#d4eee5;font-size:16px;">Your fitness journey starts here.</p>
        </div>
        <div style="padding:32px;">
          <p style="margin:0 0 20px;line-height:1.6;">Your client profile is ready. Keep your client ID handy when visiting the gym.</p>
          <div style="padding:20px;border-radius:12px;background:#f0f7f4;text-align:center;">
            <div style="font-size:12px;color:#52645e;letter-spacing:1px;text-transform:uppercase;">Your Client ID</div>
            <div style="margin-top:8px;color:#123c35;font-size:30px;font-weight:bold;">{client_id}</div>
          </div>
          <div style="margin-top:24px;padding-top:20px;border-top:1px solid #e5e7eb;">
            <div style="font-size:12px;color:#64748b;text-transform:uppercase;">Registered email</div>
            <div style="margin-top:6px;font-size:15px;">{email}</div>
          </div>
          <p style="margin:24px 0 0;color:#64748b;font-size:13px;line-height:1.6;">For your privacy, this email does not include your student or PWD ID number.</p>
        </div>
        <div style="padding:18px;background:#f8fafc;color:#64748b;text-align:center;font-size:12px;">We look forward to seeing you at GymPy.</div>
      </div>
    </div>
  </body>
</html>
"""
    payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": client["email"], "name": client["name"]}],
        "subject": f"Welcome to GymPy, {client['name']}!",
        "htmlContent": html_content,
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
    except HTTPError as error:
        raise RuntimeError(
            f"Brevo rejected the welcome email (HTTP {error.code})."
        ) from error
    except (OSError, URLError, TimeoutError) as error:
        raise RuntimeError(f"Could not connect to Brevo: {error}") from error
