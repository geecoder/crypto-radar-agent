"""Tests for Telegram alert helpers."""

from types import SimpleNamespace

import requests

from app.alerts import telegram


class FakeResponse:
    """Small fake response object for Telegram tests."""

    def raise_for_status(self) -> None:
        """Pretend the request succeeded."""


def test_send_telegram_message_returns_false_when_disabled(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        telegram,
        "settings",
        SimpleNamespace(
            telegram_alerts_enabled=False,
            telegram_bot_token="token",
            telegram_chat_id="chat",
        ),
    )

    result = telegram.send_telegram_message("hello")

    assert result is False
    assert "Telegram alerts disabled." in capsys.readouterr().out


def test_send_telegram_message_returns_false_when_credentials_missing(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        telegram,
        "settings",
        SimpleNamespace(
            telegram_alerts_enabled=True,
            telegram_bot_token="",
            telegram_chat_id="",
        ),
    )

    result = telegram.send_telegram_message("hello")

    assert result is False
    assert "bot token or chat ID is missing" in capsys.readouterr().out


def test_send_telegram_message_posts_to_telegram(monkeypatch) -> None:
    requests_made = []
    monkeypatch.setattr(
        telegram,
        "settings",
        SimpleNamespace(
            telegram_alerts_enabled=True,
            telegram_bot_token="token",
            telegram_chat_id="chat",
        ),
    )

    def fake_post(url: str, data: dict, timeout: int) -> FakeResponse:
        requests_made.append({"url": url, "data": data, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr(telegram.requests, "post", fake_post)

    result = telegram.send_telegram_message("hello")

    assert result is True
    assert requests_made == [
        {
            "url": "https://api.telegram.org/bottoken/sendMessage",
            "data": {
                "chat_id": "chat",
                "text": "hello",
                "parse_mode": "HTML",
            },
            "timeout": 20,
        }
    ]


def test_send_telegram_message_returns_false_on_request_error(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        telegram,
        "settings",
        SimpleNamespace(
            telegram_alerts_enabled=True,
            telegram_bot_token="token",
            telegram_chat_id="chat",
        ),
    )

    def fake_post(url: str, data: dict, timeout: int) -> FakeResponse:
        raise requests.RequestException("network failed")

    monkeypatch.setattr(telegram.requests, "post", fake_post)

    result = telegram.send_telegram_message("hello")

    assert result is False
    assert "Failed to send Telegram message" in capsys.readouterr().out
