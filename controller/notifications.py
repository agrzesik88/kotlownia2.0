from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import smtplib
from email.message import EmailMessage


@dataclass(frozen=True, slots=True)
class EmailConfig:
    enabled: bool
    smtp_host: str
    smtp_port: int
    use_starttls: bool
    username_env: str
    password_env: str
    sender: str
    recipients: tuple[str, ...]


class NotificationService:
    """Logowanie i opcjonalne powiadomienia e-mail bez wpływu na automatykę."""

    def __init__(
        self,
        email_config: EmailConfig | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self.email_config = email_config

    def info(self, message: str) -> None:
        self.logger.info(message)

    def warning(self, message: str) -> None:
        self.logger.warning(message)

    def error(self, message: str) -> None:
        self.logger.error(message)

    def send_email(self, subject: str, body: str) -> bool:
        config = self.email_config
        if config is None or not config.enabled:
            self.logger.info("E-mail wyłączony: %s", subject)
            return False

        username = os.getenv(config.username_env, "")
        password = os.getenv(config.password_env, "")
        if not username or not password:
            self.logger.error(
                "Brak danych SMTP w zmiennych %s/%s",
                config.username_env,
                config.password_env,
            )
            return False
        if not config.sender or not config.recipients:
            self.logger.error("Brak nadawcy lub odbiorców wiadomości e-mail")
            return False

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = config.sender
        message["To"] = ", ".join(config.recipients)
        message.set_content(body)

        try:
            with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=15) as smtp:
                if config.use_starttls:
                    smtp.starttls()
                smtp.login(username, password)
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            self.logger.exception("Nie udało się wysłać e-maila: %s", exc)
            return False

        self.logger.info("Wysłano e-mail: %s", subject)
        return True
