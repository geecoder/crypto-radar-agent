"""Tests for application command-line behavior."""

import sys
from types import SimpleNamespace

from app import main as app_main


def test_main_sends_telegram_test_message_and_exits(monkeypatch, capsys) -> None:
    messages = []

    monkeypatch.setattr(sys, "argv", ["python -m app.main", "--test-telegram"])
    monkeypatch.setattr(app_main, "send_telegram_message", messages.append)
    monkeypatch.setattr(
        app_main,
        "append_alert_history",
        lambda result, telegram_sent: (_ for _ in ()).throw(
            AssertionError("Alert history should not be written in test mode.")
        ),
    )

    def fail_if_scanner_starts():
        raise AssertionError("Scanner should not start in Telegram test mode.")

    monkeypatch.setattr(app_main, "BinancePublicClient", fail_if_scanner_starts)

    app_main.main()

    assert messages == [app_main.TELEGRAM_TEST_MESSAGE]
    assert "Crypto Radar Agent started" in capsys.readouterr().out


def test_main_checks_outcomes_and_exits(monkeypatch, capsys) -> None:
    saved_outcomes = []
    alert_history = [
        {
            "id": "BTCUSDT-2026-05-14T00:00:00+00:00",
            "symbol": "BTCUSDT",
            "latest_close": 100.0,
        }
    ]
    outcomes = [
        {
            "symbol": "BTCUSDT",
            "hit_5pct": True,
            "hit_10pct": True,
            "hit_20pct": False,
            "hit_50pct": False,
            "hit_100pct": False,
        }
    ]
    fake_client = object()

    monkeypatch.setattr(sys, "argv", ["python -m app.main", "--check-outcomes"])
    monkeypatch.setattr(app_main, "load_alert_history", lambda: alert_history)
    monkeypatch.setattr(app_main, "BinancePublicClient", lambda: fake_client)
    monkeypatch.setattr(
        app_main,
        "check_alert_outcomes",
        lambda history, client: outcomes,
    )
    monkeypatch.setattr(
        app_main,
        "save_alert_outcomes",
        lambda records: saved_outcomes.extend(records),
    )
    monkeypatch.setattr(
        app_main,
        "scan_symbols",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Scanner should not run in outcome-check mode.")
        ),
    )

    app_main.main()

    output = capsys.readouterr().out

    assert saved_outcomes == outcomes
    assert "Crypto Radar Agent started" in output
    assert "Outcome check completed." in output
    assert "Alerts checked: 1" in output
    assert "Outcomes saved: 1" in output
    assert "Hit +5%: 1" in output
    assert "Hit +10%: 1" in output
    assert "Hit +20%: 0" in output
    assert "Hit +50%: 0" in output
    assert "Hit +100%: 0" in output


def test_main_prints_performance_report_and_exits(monkeypatch, capsys) -> None:
    outcomes = {
        "BTCUSDT-1": {
            "symbol": "BTCUSDT",
            "checkpoints": {"+5%": {"status": "completed"}},
            "hit_5_pct": True,
        }
    }

    monkeypatch.setattr(sys, "argv", ["python -m app.main", "--performance-report"])
    monkeypatch.setattr(app_main, "load_alert_outcomes", lambda: outcomes)
    monkeypatch.setattr(
        app_main,
        "scan_symbols",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Scanner should not run in performance-report mode.")
        ),
    )

    app_main.main()

    output = capsys.readouterr().out

    assert "Crypto Radar Agent started" in output
    assert "Crypto Radar Performance Report" in output
    assert "Total outcomes: 1" in output
    assert "Hit +5%: 1 (100%)" in output


def test_main_sends_performance_report_to_telegram(monkeypatch, capsys) -> None:
    sent_messages = []
    outcomes = {
        "BTCUSDT-1": {
            "symbol": "BTCUSDT",
            "checkpoints": {"+5%": {"status": "completed"}},
            "hit_5_pct": True,
        }
    }

    def fake_send_telegram_message(message: str) -> bool:
        sent_messages.append(message)
        return True

    monkeypatch.setattr(
        sys,
        "argv",
        ["python -m app.main", "--send-performance-report"],
    )
    monkeypatch.setattr(app_main, "load_alert_outcomes", lambda: outcomes)
    monkeypatch.setattr(app_main, "send_telegram_message", fake_send_telegram_message)
    monkeypatch.setattr(
        app_main,
        "scan_symbols",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Scanner should not run in send-performance-report mode.")
        ),
    )

    app_main.main()

    output = capsys.readouterr().out

    assert "Crypto Radar Agent started" in output
    assert "Performance report sent to Telegram." in output
    assert len(sent_messages) == 1
    assert "Crypto Radar Performance Report" in sent_messages[0]


def test_main_prints_failure_when_performance_report_telegram_send_fails(
    monkeypatch,
    capsys,
) -> None:
    outcomes = {
        "BTCUSDT-1": {
            "symbol": "BTCUSDT",
            "checkpoints": {"+5%": {"status": "completed"}},
        }
    }

    monkeypatch.setattr(
        sys,
        "argv",
        ["python -m app.main", "--send-performance-report"],
    )
    monkeypatch.setattr(app_main, "load_alert_outcomes", lambda: outcomes)
    monkeypatch.setattr(app_main, "send_telegram_message", lambda message: False)
    monkeypatch.setattr(
        app_main,
        "scan_symbols",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Scanner should not run in send-performance-report mode.")
        ),
    )

    app_main.main()

    output = capsys.readouterr().out

    assert "Crypto Radar Agent started" in output
    assert "Failed to send performance report to Telegram." in output


def test_main_prints_signal_analysis_and_exits(monkeypatch, capsys) -> None:
    outcomes = {
        "BTCUSDT-1": {
            "symbol": "BTCUSDT",
            "checkpoints": {"+5%": {"status": "completed"}},
            "opportunity_score": 80,
            "max_upside_pct": 20,
            "max_drawdown_pct": -5,
            "move_stage_signal": {"stage": "Stage 3 - Confirmed early momentum"},
        }
    }

    monkeypatch.setattr(sys, "argv", ["python -m app.main", "--signal-analysis"])
    monkeypatch.setattr(app_main, "load_alert_outcomes", lambda: outcomes)
    monkeypatch.setattr(
        app_main,
        "scan_symbols",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Scanner should not run in signal-analysis mode.")
        ),
    )

    app_main.main()

    output = capsys.readouterr().out

    assert "Crypto Radar Agent started" in output
    assert "Crypto Radar Signal Analysis" in output
    assert "Performance by Move Stage" in output
    assert "Stage 3 - Confirmed early momentum" in output


def test_main_updates_paper_trades_and_exits(monkeypatch, capsys) -> None:
    fake_client = object()
    summary = {
        "open_trades_checked": 2,
        "closed_trades": 1,
        "still_open": 1,
    }

    monkeypatch.setattr(sys, "argv", ["python -m app.main", "--update-paper-trades"])
    monkeypatch.setattr(app_main, "BinancePublicClient", lambda: fake_client)
    monkeypatch.setattr(
        app_main,
        "update_open_paper_trades",
        lambda client: summary if client is fake_client else {},
    )
    monkeypatch.setattr(
        app_main,
        "scan_symbols",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Scanner should not run in paper-trade update mode.")
        ),
    )

    app_main.main()

    output = capsys.readouterr().out

    assert "Crypto Radar Agent started" in output
    assert "Paper trade update completed." in output
    assert "Open trades checked: 2" in output
    assert "Closed trades: 1" in output
    assert "Still open: 1" in output


def test_main_sends_alert_message_when_candidates_exist(monkeypatch, capsys) -> None:
    sent_messages = []
    recorded_alerts = []
    alert_history_records = []
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
        lambda client, symbols, interval="15m", limit=100, max_symbols=50, tickers_24hr=None: [candidate],
    )
    monkeypatch.setattr(app_main, "should_send_alert", lambda symbol, score: (True, "ok"))

    def fake_send_telegram_message(message: str) -> bool:
        sent_messages.append(message)
        return True

    monkeypatch.setattr(app_main, "send_telegram_message", fake_send_telegram_message)
    monkeypatch.setattr(
        app_main,
        "record_alert",
        lambda symbol, score: recorded_alerts.append((symbol, score)),
    )
    monkeypatch.setattr(
        app_main,
        "append_alert_history",
        lambda result, telegram_sent: alert_history_records.append(
            (result["symbol"], telegram_sent)
        ),
    )

    app_main.main()

    output = capsys.readouterr().out

    assert "Alert candidates:" in output
    assert len(sent_messages) == 1
    assert "Crypto Radar Alert Candidates" in sent_messages[0]
    assert "BTCUSDT" in sent_messages[0]
    assert recorded_alerts == [("BTCUSDT", 72)]
    assert alert_history_records == [("BTCUSDT", True)]


def test_main_logs_alert_history_when_telegram_send_fails(monkeypatch, capsys) -> None:
    recorded_alerts = []
    alert_history_records = []
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
        lambda client, symbols, interval="15m", limit=100, max_symbols=50, tickers_24hr=None: [candidate],
    )
    monkeypatch.setattr(app_main, "should_send_alert", lambda symbol, score: (True, "ok"))
    monkeypatch.setattr(app_main, "send_telegram_message", lambda message: False)
    monkeypatch.setattr(
        app_main,
        "record_alert",
        lambda symbol, score: recorded_alerts.append((symbol, score)),
    )
    monkeypatch.setattr(
        app_main,
        "append_alert_history",
        lambda result, telegram_sent: alert_history_records.append(
            (result["symbol"], telegram_sent)
        ),
    )

    app_main.main()

    output = capsys.readouterr().out

    assert "Alert candidates:" in output
    assert recorded_alerts == []
    assert alert_history_records == [("BTCUSDT", False)]


def test_main_does_not_send_alert_message_when_no_candidates(monkeypatch, capsys) -> None:
    sent_messages = []
    alert_history_records = []
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
        lambda client, symbols, interval="15m", limit=100, max_symbols=50, tickers_24hr=None: [weak_setup],
    )
    monkeypatch.setattr(app_main, "send_telegram_message", sent_messages.append)
    monkeypatch.setattr(
        app_main,
        "append_alert_history",
        lambda result, telegram_sent: alert_history_records.append(
            (result["symbol"], telegram_sent)
        ),
    )

    app_main.main()

    output = capsys.readouterr().out

    assert sent_messages == []
    assert alert_history_records == []
    assert "No Telegram alert sent." in output
    assert "Best weak setups:" in output


def test_main_suppresses_alert_candidates_during_cooldown(monkeypatch, capsys) -> None:
    sent_messages = []
    recorded_alerts = []
    alert_history_records = []
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
        lambda client, symbols, interval="15m", limit=100, max_symbols=50, tickers_24hr=None: [candidate],
    )
    monkeypatch.setattr(
        app_main,
        "should_send_alert",
        lambda symbol, score: (False, "Duplicate alert suppressed during cooldown."),
    )
    monkeypatch.setattr(app_main, "send_telegram_message", sent_messages.append)
    monkeypatch.setattr(
        app_main,
        "record_alert",
        lambda symbol, score: recorded_alerts.append((symbol, score)),
    )
    monkeypatch.setattr(
        app_main,
        "append_alert_history",
        lambda result, telegram_sent: alert_history_records.append(
            (result["symbol"], telegram_sent)
        ),
    )

    app_main.main()

    output = capsys.readouterr().out

    assert sent_messages == []
    assert recorded_alerts == []
    assert alert_history_records == []
    assert "BTCUSDT: Duplicate alert suppressed during cooldown." in output
    assert "Alert candidates found, but all were suppressed by cooldown." in output
