"""Send the daily report via SMTP email."""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from . import config

logger = logging.getLogger(__name__)


def send_email(html_body: str, subject: str) -> None:
    """Send an HTML email using the configured SMTP server.

    Parameters
    ----------
    html_body:
        Rendered HTML content for the email body.
    subject:
        Email subject line.

    Raises
    ------
    RuntimeError
        If required SMTP configuration is missing.
    smtplib.SMTPException
        On mail-delivery errors.
    """
    # Validate configuration
    missing = []
    if not config.SMTP_HOST:
        missing.append("SMTP_HOST")
    if not config.SMTP_USER:
        missing.append("SMTP_USER")
    if not config.SMTP_PASSWORD:
        missing.append("SMTP_PASSWORD")
    if not config.EMAIL_TO:
        missing.append("EMAIL_TO")
    if missing:
        raise RuntimeError(
            f"Email not sent — missing environment variables: {', '.join(missing)}"
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.SMTP_USER
    msg["To"] = config.EMAIL_TO

    # Attach HTML part
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    logger.info(
        "Sending email to %s via %s:%s …",
        config.EMAIL_TO,
        config.SMTP_HOST,
        config.SMTP_PORT,
    )

    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(config.SMTP_USER, config.SMTP_PASSWORD)
        server.sendmail(config.SMTP_USER, config.EMAIL_TO.split(","), msg.as_string())

    logger.info("Email sent successfully ✅")
