"""
Optional email notifications.
"""
import logging
import smtplib
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def send_email(
    to_addr: str,
    subject: str,
    body: str,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_pass: str,
):
    if not all([to_addr, smtp_host, smtp_user, smtp_pass]):
        return  # notifications not configured

    msg = MIMEText(body)
    msg["Subject"] = f"[tqqq-bot] {subject}"
    msg["From"] = smtp_user
    msg["To"] = to_addr

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as s:
            s.starttls()
            s.login(smtp_user, smtp_pass)
            s.send_message(msg)
        logger.info("Notification email sent to %s", to_addr)
    except Exception as exc:
        logger.warning("Failed to send notification email: %s", exc)
