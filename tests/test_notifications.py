from __future__ import annotations

import smtplib

from controller.notifications import EmailConfig, NotificationService


class FakeSMTP:
    last_message = None

    def __init__(self, host: str, port: int, timeout: int) -> None:
        assert host == "smtp.gmail.com"
        assert port == 587
        assert timeout == 15

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def starttls(self) -> None:
        pass

    def login(self, username: str, password: str) -> None:
        assert username == "raspberrypieddy88@gmail.com"
        assert password == "test-app-password"

    def send_message(self, message) -> None:
        FakeSMTP.last_message = message


def test_email_is_sent_to_all_recipients(monkeypatch) -> None:
    monkeypatch.setenv("KOTLOWNIA_SMTP_USERNAME", "raspberrypieddy88@gmail.com")
    monkeypatch.setenv("KOTLOWNIA_SMTP_PASSWORD", "test-app-password")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    service = NotificationService(
        EmailConfig(
            enabled=True,
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            use_starttls=True,
            username_env="KOTLOWNIA_SMTP_USERNAME",
            password_env="KOTLOWNIA_SMTP_PASSWORD",
            sender="raspberrypieddy88@gmail.com",
            recipients=("aeddy88@gmail.com", "elwira.grzesik83@gmail.com"),
        )
    )

    assert service.send_email("Kotłownia 2.0: niski poziom pelletu", "Czas uzupełnić pellet!")
    assert FakeSMTP.last_message["From"] == "raspberrypieddy88@gmail.com"
    assert FakeSMTP.last_message["To"] == "aeddy88@gmail.com, elwira.grzesik83@gmail.com"
    assert FakeSMTP.last_message["Subject"] == "Kotłownia 2.0: niski poziom pelletu"
    assert "Czas uzupełnić pellet!" in FakeSMTP.last_message.get_content()


def test_email_is_not_sent_without_credentials(monkeypatch) -> None:
    monkeypatch.delenv("KOTLOWNIA_SMTP_USERNAME", raising=False)
    monkeypatch.delenv("KOTLOWNIA_SMTP_PASSWORD", raising=False)

    service = NotificationService(
        EmailConfig(
            enabled=True,
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            use_starttls=True,
            username_env="KOTLOWNIA_SMTP_USERNAME",
            password_env="KOTLOWNIA_SMTP_PASSWORD",
            sender="raspberrypieddy88@gmail.com",
            recipients=("aeddy88@gmail.com",),
        )
    )

    assert service.send_email("test", "body") is False
