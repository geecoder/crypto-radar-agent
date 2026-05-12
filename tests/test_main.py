"""Tests for application command-line behavior."""

import sys
from types import SimpleNamespace

from app import main as app_main


def test_main_sends_telegram_test_message_and_exits(monkeypatch, capsys) -> None:
    messages = []

    monkeypatch.setattr(sys, "argv", ["python -m app.main", "--test-telegram"])
    monkeypatch.setattr(app_main, "send_telegram_message", messages.append)

    def fail_if_scanner_starts():
        raise AssertionError("Scanner should not start in Telegram test mode.")

    monkeypatch.setattr(app_main, "BinancePublicClient", fail_if_scanner_starts)

    app_main.main()

    assert messages == [app_main.TELEGRAM_TEST_MESSAGE]
    assert "Crypto Radar Agent started" in capsys.readouterr().out


def test_main_sends_alert_message_when_candidates_exist(monkeypatch, capsys) -> None:
    sent_messages = []
    candidate = {
        "symbol": "BTCUSDT",
        "latest_close": 100.0,
        "opportunity": {
            "opportunity_score": 72,
            "classification": "Watchlist",
            "target_bucket": "+20% momentum setup",
            "risk_level": "Medium",
            "summary": "Watchlist. Some signals are improving.",
        },
    }

    fake_client = SimpleNamespace(
        get_exchange_info=lambda: {"symbols": []},
        get_24hr_tickers=lambda: [],
    )

    monkeypatch.setattr(sys, "argv", ["python -m app.main"])
    monkeypatch.setattr(app_main, "BinancePublicClient", lambda: fake_client)
    monkeypatch.setattr(app_main, "get_active_usdt_symbols", lambda exchange_info: ["BTCUSDT"])
    monkeypatch.setattr(
        app_main,
        "select_priority_symbols",
        lambda active_symbols, tickers_24hr, max_symbols=50: ["BTCUSDT"],
    )
    monkeypatch.setattr(
        app_main,
        "scan_symbols",
        lambda client, symbols, interval="15m", limit=100, max_symbols=50: [candidate],
    )
    monkeypatch.setattr(app_main, "send_telegram_message", sent_messages.append)

    app_main.main()

    output = capsys.readouterr().out

    assert "Alert candidates:" in output
    assert len(sent_messages) == 1
    assert "Crypto Radar Alert Candidates" in sent_messages[0]
    assert "BTCUSDT" in sent_messages[0]


def test_main_does_not_send_alert_message_when_no_candidates(monkeypatch, capsys) -> None:
    sent_messages = []
    weak_setup = {
        "symbol": "ETHUSDT",
        "latest_close": 50.0,
        "opportunity": {
            "opportunity_score": 35,
            "classification": "Ignore",
            "target_bucket": "No clear upside setup",
            "risk_level": "Low",
            "summary": "Signals are weak.",
        },
    }

    fake_client = SimpleNamespace(
        get_exchange_info=lambda: {"symbols": []},
        get_24hr_tickers=lambda: [],
    )

    monkeypatch.setattr(sys, "argv", ["python -m app.main"])
    monkeypatch.setattr(app_main, "BinancePublicClient", lambda: fake_client)
    monkeypatch.setattr(app_main, "get_active_usdt_symbols", lambda exchange_info: ["ETHUSDT"])
    monkeypatch.setattr(
        app_main,
        "select_priority_symbols",
        lambda active_symbols, tickers_24hr, max_symbols=50: ["ETHUSDT"],
    )
    monkeypatch.setattr(
        app_main,
        "scan_symbols",
        lambda client, symbols, interval="15m", limit=100, max_symbols=50: [weak_setup],
    )
    monkeypatch.setattr(app_main, "send_telegram_message", sent_messages.append)

    app_main.main()

    output = capsys.readouterr().out

    assert sent_messages == []
    assert "No Telegram alert sent." in output
    assert "Best weak setups:" in output
