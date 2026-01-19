import smtplib
from email.message import EmailMessage
from app.config import (
    ALERT_EMAIL_TO,
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USER,
    SMTP_PASSWORD,
)


def send_unhealthy_alert(server_name: str) -> None:
    if not all([ALERT_EMAIL_TO, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD]):
        print("[email] missing email configuration, skipping alert")
        return

    msg = EmailMessage()
    msg["Subject"] = f"[ALERT] Server {server_name} is UNHEALTHY"
    msg["From"] = SMTP_USER
    msg["To"] = ALERT_EMAIL_TO

    msg.set_content(
        f"The server '{server_name}' has become UNHEALTHY.\n"
        f"Please check immediately."
    )

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.starttls()
        smtp.login(SMTP_USER, SMTP_PASSWORD)
        smtp.send_message(msg)

    print(f"[email] alert sent for server '{server_name}'")
