"""Tests for Telegram alert helpers."""

from types import SimpleNamespace

import requests

from app.alerts import telegram


class FakeResponse:
    """Small fake response object for Telegram tests."""

    def __init__(self, status_code: int = 200, text: str = '{"ok": true}') -> None:
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        """Pretend the request succeeded."""

    def json(self) -> dict:
        import json
        return json.loads(self.text)


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

    sent, attempts = telegram.send_telegram_message("hello")

    assert sent is False
    assert attempts == []
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

    sent, attempts = telegram.send_telegram_message("hello")

    assert sent is False
    assert attempts == []
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
        return FakeResponse(status_code=200)

    monkeypatch.setattr(telegram.requests, "post", fake_post)

    sent, attempts = telegram.send_telegram_message("hello")

    assert sent is True
    assert len(attempts) == 1
    assert attempts[0].http_status == 200
    assert attempts[0].success is True
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

    sent, attempts = telegram.send_telegram_message("hello")

    assert sent is False
    # All retry attempts recorded, all failed
    assert len(attempts) > 0
    assert all(not a.success for a in attempts)
    assert "network failed" in capsys.readouterr().out
