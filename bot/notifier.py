"""
Optional email notifications.
"""
import logging
import smtplib
import traceback
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

logger = logging.getLogger(__name__)


def _send(msg: MIMEMultipart | MIMEText, smtp_host: str, smtp_port: int, smtp_user: str, smtp_pass: str, to_addr: str):
    try:
        with smtplib.SMTP(smtp_host, smtp_port) as s:
            s.starttls()
            s.login(smtp_user, smtp_pass)
            s.send_message(msg)
        logger.info("Notification email sent to %s", to_addr)
    except Exception as exc:
        logger.warning("Failed to send notification email: %s", exc)


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
        return

    msg = MIMEText(body)
    msg["Subject"] = f"[tqqq-bot] {subject}"
    msg["From"] = smtp_user
    msg["To"] = to_addr
    _send(msg, smtp_host, smtp_port, smtp_user, smtp_pass, to_addr)


def send_run_result(success: bool, cfg, exc: Exception = None):
    if not all([cfg.NOTIFY_EMAIL, cfg.SMTP_HOST, cfg.SMTP_USER, cfg.SMTP_PASS]):
        return

    if success:
        msg = MIMEText("tqqq-bot completed successfully. Check trade emails for any actions taken.")
        msg["Subject"] = "[tqqq-bot] Run complete"
        msg["From"] = cfg.SMTP_USER
        msg["To"] = cfg.NOTIFY_EMAIL
    else:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        msg = MIMEMultipart()
        msg["Subject"] = "[tqqq-bot] Run FAILED"
        msg["From"] = cfg.SMTP_USER
        msg["To"] = cfg.NOTIFY_EMAIL
        msg.attach(MIMEText(f"tqqq-bot encountered an error:\n\n{tb}"))

        log_path = Path(cfg.LOG_PATH)
        if log_path.exists():
            with open(log_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{log_path.name}"')
            msg.attach(part)

    _send(msg, cfg.SMTP_HOST, cfg.SMTP_PORT, cfg.SMTP_USER, cfg.SMTP_PASS, cfg.NOTIFY_EMAIL)
