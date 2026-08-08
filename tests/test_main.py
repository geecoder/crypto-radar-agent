"""Tests for application command-line behavior."""

import sys
from types import SimpleNamespace

from app import main as app_main


def test_main_sends_telegram_test_message_and_exits(monkeypatch, capsys) -> None:
    messages = []

    monkeypatch.setattr(sys, "argv", ["python -m app.main", "--test-telegram"])
    monkeypatch.setattr(app_main, "send_telegram_message", lambda msg: (True, messages.append(msg) or []))
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
    monkeypatch.setattr(app_main, "load_alert_history", lambda limit=None: alert_history)
    monkeypatch.setattr(app_main, "BinancePublicClient", lambda: fake_client)
    monkeypatch.setattr(
        app_main,
        "check_alert_outcomes",
        lambda history, client, deadline=None: outcomes,
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


def test_check_outcomes_prints_invalid_supabase_url_without_traceback(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(sys, "argv", ["python -m app.main", "--check-outcomes"])
    monkeypatch.setattr(
        app_main,
        "load_alert_history",
        lambda limit=None: (_ for _ in ()).throw(
            RuntimeError(app_main.INVALID_SUPABASE_DATABASE_URL_MESSAGE)
        ),
    )
    monkeypatch.setattr(
        app_main,
        "BinancePublicClient",
        lambda: (_ for _ in ()).throw(
            AssertionError("Binance client should not start after DSN validation fails.")
        ),
    )

    app_main.main()

    output = capsys.readouterr().out

    assert app_main.INVALID_SUPABASE_DATABASE_URL_MESSAGE in output
    assert "Traceback" not in output


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

    def fake_send_telegram_message(message: str) -> tuple:
        sent_messages.append(message)
        return True, []

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
    monkeypatch.setattr(app_main, "send_telegram_message", lambda message: (False, []))
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


def test_main_repairs_stale_paper_trades_and_exits(monkeypatch, capsys) -> None:
    fake_client = object()
    summary = {
        "open_trades_checked": 3,
        "closed_trades": 2,
        "closed_stop_loss": 0,
        "closed_take_profit": 0,
        "closed_max_hold": 2,
        "still_open": 1,
        "errors": 0,
    }

    monkeypatch.setattr(
        sys,
        "argv",
        ["python -m app.main", "--repair-stale-paper-trades"],
    )
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
            AssertionError("Scanner should not run in stale repair mode.")
        ),
    )

    app_main.main()

    output = capsys.readouterr().out

    assert "Crypto Radar Agent started" in output
    assert "Stale paper trade repair completed." in output
    assert "Closed max hold: 2" in output


def test_main_prints_paper_trading_report_and_exits(monkeypatch, capsys) -> None:
    paper_trades = [
        {
            "symbol": "BTCUSDT",
            "status": "closed",
            "pnl_pct": 8,
            "pnl_amount": 8,
            "exit_reason": "take_profit_1",
        }
    ]

    monkeypatch.setattr(sys, "argv", ["python -m app.main", "--paper-trading-report"])
    monkeypatch.setattr(app_main, "load_all_paper_trades", lambda: paper_trades)
    monkeypatch.setattr(
        app_main,
        "scan_symbols",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Scanner should not run in paper-trading-report mode.")
        ),
    )

    app_main.main()

    output = capsys.readouterr().out

    assert "Crypto Radar Agent started" in output
    assert "Crypto Radar Paper Trading Report" in output
    assert "Total trades: 1" in output
    assert "Average P/L: 8%" in output


def test_main_prints_telegram_delivery_report_and_exits(monkeypatch, capsys) -> None:
    alert_history = [{"telegram_sent": True}]

    monkeypatch.setattr(
        sys,
        "argv",
        ["python -m app.main", "--telegram-delivery-report"],
    )
    monkeypatch.setattr(app_main, "load_alert_history", lambda: alert_history)
    monkeypatch.setattr(
        app_main,
        "scan_symbols",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Scanner should not run in Telegram delivery report mode.")
        ),
    )

    app_main.main()

    output = capsys.readouterr().out

    assert "Crypto Radar Agent started" in output
    assert "Crypto Radar Telegram Delivery Report" in output
    assert "Total alerts reviewed: 1" in output


def test_main_sends_telegram_delivery_report(monkeypatch, capsys) -> None:
    sent_messages = []

    monkeypatch.setattr(
        sys,
        "argv",
        ["python -m app.main", "--send-telegram-delivery-report"],
    )
    monkeypatch.setattr(app_main, "load_alert_history", lambda: [{"telegram_sent": True}])
    monkeypatch.setattr(
        app_main,
        "send_telegram_message",
        lambda message: (sent_messages.append(message) or True, []),
    )
    monkeypatch.setattr(
        app_main,
        "scan_symbols",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Scanner should not run in send delivery report mode.")
        ),
    )

    app_main.main()

    output = capsys.readouterr().out

    assert "Telegram delivery report sent to Telegram." in output
    assert len(sent_messages) == 1
    assert "Crypto Radar Telegram Delivery Report" in sent_messages[0]


def test_main_prints_live_readiness_report_and_exits(monkeypatch, capsys) -> None:
    paper_trades = [
        {
            "symbol": "BTCUSDT",
            "status": "closed",
            "pnl_pct": 8,
            "pnl_amount": 8,
            "exit_reason": "take_profit_1",
        }
    ]

    monkeypatch.setattr(sys, "argv", ["python -m app.main", "--live-readiness-report"])
    monkeypatch.setattr(app_main, "USE_SUPABASE", False)
    monkeypatch.setattr(app_main, "load_all_paper_trades", lambda: paper_trades)
    monkeypatch.setattr(app_main, "load_alert_history", lambda: [])
    monkeypatch.setattr(
        app_main,
        "scan_symbols",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Scanner should not run in live-readiness-report mode.")
        ),
    )

    app_main.main()

    output = capsys.readouterr().out

    assert "Crypto Radar Agent started" in output
    assert "Crypto Radar Live Readiness Report" in output
    assert "Status: NOT_READY" in output
    assert "Total paper trades: 1" in output


def test_main_prints_symbol_diagnostic_and_exits(monkeypatch, capsys) -> None:
    fake_client = object()
    diagnostic_result = {
        "symbol": "ENJUSDT",
        "opportunity": {"opportunity_score": 55},
    }
    diagnose_calls = []

    monkeypatch.setattr(
        sys,
        "argv",
        ["python -m app.main", "--diagnose-symbol", "ENJUSDT"],
    )
    monkeypatch.setattr(app_main, "BinancePublicClient", lambda: fake_client)
    monkeypatch.setattr(
        app_main,
        "diagnose_symbol",
        lambda client, symbol, alert_threshold=60: diagnose_calls.append(
            (client, symbol, alert_threshold)
        )
        or diagnostic_result,
    )
    monkeypatch.setattr(
        app_main,
        "format_diagnostic_report",
        lambda result, alert_threshold=60: "Missed Mover Diagnostic\nSymbol: ENJUSDT",
    )
    monkeypatch.setattr(
        app_main,
        "scan_symbols",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Scanner should not run in diagnose mode.")
        ),
    )

    app_main.main()

    output = capsys.readouterr().out

    assert diagnose_calls == [(fake_client, "ENJUSDT", app_main.ALERT_THRESHOLD)]
    assert "Crypto Radar Agent started" in output
    assert "Missed Mover Diagnostic" in output
    assert "Symbol: ENJUSDT" in output


def test_parse_args_accepts_persistence_health_check(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["python -m app.main", "--persistence-health-check"],
    )

    args = app_main.parse_args()

    assert args.persistence_health_check is True


def test_main_prints_persistence_health_check_and_exits(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["python -m app.main", "--persistence-health-check"],
    )
    monkeypatch.setattr(
        app_main,
        "persistence_health_check",
        lambda: {"backend": "json"},
    )
    monkeypatch.setattr(
        app_main,
        "format_persistence_health_check",
        lambda report: f"Persistence Health Check\nBackend: {report['backend']}",
    )
    monkeypatch.setattr(
        app_main,
        "scan_symbols",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Scanner should not run in persistence-health-check mode.")
        ),
    )

    app_main.main()

    output = capsys.readouterr().out

    assert "Crypto Radar Agent started" in output
    assert "Persistence Health Check" in output
    assert "Backend: json" in output


def test_main_passes_selected_paper_strategy_to_trade_creation(monkeypatch) -> None:
    captured_strategy_names = []
    candidate = {
        "symbol": "BTCUSDT",
        "latest_close": 100.0,
        "opportunity": {
            "opportunity_score": 80,
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

    monkeypatch.setattr(
        sys,
        "argv",
        ["python -m app.main", "--paper-strategy", "conservative"],
    )
    monkeypatch.setattr(app_main, "BinancePublicClient", lambda: fake_client)
    monkeypatch.setattr(app_main, "get_active_usdt_symbols", lambda exchange_info: ["BTCUSDT"])
    monkeypatch.setattr(
        app_main,
        "select_scan_universe",
        lambda active_symbols, tickers_24hr, max_priority_symbols=50, max_universe_symbols=150: ["BTCUSDT"],
    )
    monkeypatch.setattr(
        app_main,
        "scan_symbols",
        lambda client, symbols, interval="15m", limit=100, max_symbols=50, tickers_24hr=None: [candidate],
    )
    monkeypatch.setattr(app_main, "should_send_alert", lambda symbol, score, **_: (True, "ok"))
    monkeypatch.setattr(app_main, "send_telegram_message", lambda message: (True, []))
    monkeypatch.setattr(
        app_main,
        "append_alert_history",
        lambda result, telegram_sent: {"id": "alert-1"},
    )
    monkeypatch.setattr(app_main, "record_alert", lambda symbol, score, **_: None)

    def fake_create_paper_trades_from_alerts(alert_candidates, strategy=None):
        captured_strategy_names.append(strategy.name)
        return []

    monkeypatch.setattr(
        app_main,
        "create_paper_trades_from_alerts",
        fake_create_paper_trades_from_alerts,
    )

    app_main.main()

    assert captured_strategy_names == ["conservative_momentum"]


def test_main_creates_scan_run_and_links_alert_history_when_supabase_enabled(
    monkeypatch,
) -> None:
    created_scan_runs = []
    completed_scan_runs = []
    telegram_updates = []
    alert_history_payloads = []
    paper_trade_candidates = []
    candidate = {
        "id": "source-alert-1",
        "symbol": "BTCUSDT",
        "latest_close": 100.0,
        "recent_price_changes": {"change_1h_pct": 2},
        "volume_acceleration": {"volume_acceleration_1h_ratio": 1.4},
        "trade_plan": {
            "trade_plan_type": "standard_continuation",
            "should_paper_trade": True,
        },
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
    monkeypatch.setattr(app_main, "USE_SUPABASE", True)
    monkeypatch.setattr(app_main, "BinancePublicClient", lambda: fake_client)
    monkeypatch.setattr(app_main, "get_active_usdt_symbols", lambda exchange_info: ["BTCUSDT"])
    monkeypatch.setattr(
        app_main,
        "select_scan_universe",
        lambda active_symbols, tickers_24hr, max_priority_symbols=50, max_universe_symbols=150: ["BTCUSDT"],
    )
    monkeypatch.setattr(
        app_main,
        "scan_symbols",
        lambda client, symbols, interval="15m", limit=100, max_symbols=50, tickers_24hr=None: [candidate],
    )
    monkeypatch.setattr(app_main, "should_send_alert", lambda symbol, score, **_: (True, "ok"))
    monkeypatch.setattr(app_main, "send_telegram_message", lambda message: (True, []))
    monkeypatch.setattr(app_main, "record_alert", lambda symbol, score, **_: None)
    monkeypatch.setattr(
        app_main,
        "create_scan_run",
        lambda metadata: created_scan_runs.append(metadata) or "scan-1",
    )
    monkeypatch.setattr(
        app_main,
        "complete_scan_run",
        lambda scan_run_id, summary: completed_scan_runs.append(
            (scan_run_id, summary)
        ),
    )
    monkeypatch.setattr(
        app_main,
        "update_alert_telegram_status",
        lambda alert_id, sent, error: telegram_updates.append(
            (alert_id, sent, error)
        ),
    )

    def fake_append_alert_history(result, telegram_sent):
        alert_history_payloads.append((result, telegram_sent))
        return {"id": "alert-history-1"}

    def fake_create_paper_trades_from_alerts(candidates, strategy=None):
        paper_trade_candidates.extend(candidates)
        return [
            {
                "symbol": "BTCUSDT",
                "paper_trade_created": True,
                "paper_trade_id": "paper-1",
                "decision": "created",
            }
        ]

    monkeypatch.setattr(app_main, "append_alert_history", fake_append_alert_history)
    monkeypatch.setattr(
        app_main,
        "create_paper_trades_from_alerts",
        fake_create_paper_trades_from_alerts,
    )

    app_main.main()

    assert created_scan_runs[0]["run_source"] == "local"
    assert created_scan_runs[0]["paper_strategy"] == "default_momentum_continuation"
    assert completed_scan_runs == [
        (
            "scan-1",
            {
                "total_active_symbols": 1,
                "total_scan_universe": 1,
                "total_alert_candidates": 1,
                "total_telegram_sent": 1,
                "total_paper_trades_created": 1,
                "total_paper_trades_skipped": 0,
                "status": "completed",
            },
        )
    ]
    persisted_alert, telegram_sent = alert_history_payloads[0]
    assert persisted_alert["scan_run_id"] == "scan-1"
    assert persisted_alert["recent_price_changes"] == {"change_1h_pct": 2}
    assert persisted_alert["volume_acceleration"] == {
        "volume_acceleration_1h_ratio": 1.4
    }
    assert persisted_alert["trade_plan"]["trade_plan_type"] == "standard_continuation"
    assert telegram_sent is False
    assert paper_trade_candidates[0]["alert_history_id"] == "alert-history-1"
    assert paper_trade_candidates[0]["source_alert_id"] == "source-alert-1"
    assert paper_trade_candidates[0]["scan_run_id"] == "scan-1"
    assert telegram_updates == [("alert-history-1", True, None)]


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
        "select_scan_universe",
        lambda active_symbols, tickers_24hr, max_priority_symbols=50, max_universe_symbols=150: ["BTCUSDT"],
    )
    monkeypatch.setattr(
        app_main,
        "scan_symbols",
        lambda client, symbols, interval="15m", limit=100, max_symbols=50, tickers_24hr=None: [candidate],
    )
    monkeypatch.setattr(app_main, "should_send_alert", lambda symbol, score, **_: (True, "ok"))

    def fake_send_telegram_message(message: str) -> tuple:
        sent_messages.append(message)
        return True, []

    monkeypatch.setattr(app_main, "send_telegram_message", fake_send_telegram_message)
    monkeypatch.setattr(
        app_main,
        "record_alert",
        lambda symbol, score, **_: recorded_alerts.append((symbol, score)),
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
    assert "Total scan universe selected: 1" in output
    assert "First 30 scan universe symbols: ['BTCUSDT']" in output
    assert "Scanning 1 symbols..." in output
    assert len(sent_messages) == 1
    assert "Crypto Radar Alert Candidates" in sent_messages[0]
    assert "BTCUSDT" in sent_messages[0]
    assert recorded_alerts == [("BTCUSDT", 72)]
    assert alert_history_records == [("BTCUSDT", False)]


def test_main_skips_paper_trade_for_parabolic_watch_alert(monkeypatch, capsys) -> None:
    sent_messages = []
    candidate = {
        "symbol": "EDENUSDT",
        "latest_close": 1.0,
        "alert_type": "Parabolic Watch Alert",
        "opportunity": {
            "opportunity_score": 31,
            "classification": "Ignore",
            "target_bucket": "No clear upside setup",
            "risk_level": "High",
            "summary": "High-risk market activity.",
        },
        "move_stage_signal": {
            "move_from_recent_low_pct": 78.86,
            "stage": "Stage 6 - Parabolic / high risk",
        },
        "explosive_mover": {
            "should_alert": True,
            "alert_type": "Parabolic Watch Alert",
            "potential_bucket": "High-risk parabolic watch",
            "confidence": "Medium",
            "reason": (
                "This is not a clean entry signal. It is a high-risk market "
                "activity alert."
            ),
        },
    }
    fake_client = SimpleNamespace(
        get_exchange_info=lambda: {"symbols": []},
        get_24hr_tickers=lambda: [],
    )

    monkeypatch.setattr(sys, "argv", ["python -m app.main"])
    monkeypatch.setattr(app_main, "BinancePublicClient", lambda: fake_client)
    monkeypatch.setattr(app_main, "get_active_usdt_symbols", lambda exchange_info: ["EDENUSDT"])
    monkeypatch.setattr(
        app_main,
        "select_scan_universe",
        lambda active_symbols, tickers_24hr, max_priority_symbols=50, max_universe_symbols=150: ["EDENUSDT"],
    )
    monkeypatch.setattr(
        app_main,
        "scan_symbols",
        lambda client, symbols, interval="15m", limit=100, max_symbols=50, tickers_24hr=None: [candidate],
    )
    monkeypatch.setattr(app_main, "should_send_alert", lambda symbol, score, **_: (True, "ok"))
    monkeypatch.setattr(app_main, "send_telegram_message", lambda message: (sent_messages.append(message) or True, []))
    monkeypatch.setattr(
        app_main,
        "append_alert_history",
        lambda result, telegram_sent: {"id": "alert-eden"},
    )
    monkeypatch.setattr(app_main, "record_alert", lambda symbol, score, **_: None)
    monkeypatch.setattr(app_main, "create_paper_trades_from_alerts", lambda candidates, strategy=None: [])

    app_main.main()

    output = capsys.readouterr().out

    assert len(sent_messages) == 1
    assert "Parabolic Watch Alert" in sent_messages[0]
    assert "Paper trade skipped:" in output
    assert "Paper trades created: 0" in output


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
        "select_scan_universe",
        lambda active_symbols, tickers_24hr, max_priority_symbols=50, max_universe_symbols=150: ["BTCUSDT"],
    )
    monkeypatch.setattr(
        app_main,
        "scan_symbols",
        lambda client, symbols, interval="15m", limit=100, max_symbols=50, tickers_24hr=None: [candidate],
    )
    monkeypatch.setattr(app_main, "should_send_alert", lambda symbol, score, **_: (True, "ok"))
    monkeypatch.setattr(app_main, "send_telegram_message", lambda message: (False, []))
    monkeypatch.setattr(
        app_main,
        "record_alert",
        lambda symbol, score, **_: recorded_alerts.append((symbol, score)),
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
        "select_scan_universe",
        lambda active_symbols, tickers_24hr, max_priority_symbols=50, max_universe_symbols=150: ["ETHUSDT"],
    )
    monkeypatch.setattr(
        app_main,
        "scan_symbols",
        lambda client, symbols, interval="15m", limit=100, max_symbols=50, tickers_24hr=None: [weak_setup],
    )
    monkeypatch.setattr(app_main, "send_telegram_message", lambda msg: (True, []))
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
        "select_scan_universe",
        lambda active_symbols, tickers_24hr, max_priority_symbols=50, max_universe_symbols=150: ["BTCUSDT"],
    )
    monkeypatch.setattr(
        app_main,
        "scan_symbols",
        lambda client, symbols, interval="15m", limit=100, max_symbols=50, tickers_24hr=None: [candidate],
    )
    monkeypatch.setattr(
        app_main,
        "should_send_alert",
        lambda symbol, score, **_: (False, "Duplicate alert suppressed during cooldown."),
    )
    monkeypatch.setattr(app_main, "send_telegram_message", lambda msg: (True, []))
    monkeypatch.setattr(
        app_main,
        "record_alert",
        lambda symbol, score, **_: recorded_alerts.append((symbol, score)),
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
    assert alert_history_records == [("BTCUSDT", False)]
    assert "BTCUSDT: Duplicate alert suppressed during cooldown." in output
    assert "Alert candidates found, but all were suppressed by cooldown." in output


def test_bucket_skip_reason_maps_known_reasons() -> None:
    assert app_main._bucket_skip_reason(
        "Walking the order book for $50 of BTCUSDT implies 3.00% slippage, over the 1.5% budget."
    ) == "Slippage budget exceeded"
    assert app_main._bucket_skip_reason(
        "Move from recent low must be at least 50%."
    ) == "Move-window mismatch"
    assert app_main._bucket_skip_reason("Exhaustion risk is High.") == "Exhaustion risk High"
    assert app_main._bucket_skip_reason(
        "Duplicate open paper trade exists for HEIUSDT."
    ) == "Duplicate open trade"
    assert app_main._bucket_skip_reason("") == "Not evaluated"
    assert app_main._bucket_skip_reason("Something unrecognized happened.") == "Other"


def test_movers_over_20pct_this_week_splits_traded_and_missed() -> None:
    week_cutoff = "2026-08-01T00:00:00+00:00"
    alert_history = [
        {
            "symbol": "HEIUSDT",
            "alerted_at": "2026-08-02T00:00:00+00:00",
            "move_from_recent_low_pct": 52.0,
            "paper_trade_created": True,
        },
        {
            "symbol": "CTSIUSDT",
            "alerted_at": "2026-08-03T00:00:00+00:00",
            "move_from_recent_low_pct": 41.0,
            "paper_trade_created": False,
            "paper_trade_skip_reason": "Exhaustion risk is High.",
        },
        {
            "symbol": "PONDUSDT",
            "alerted_at": "2026-08-03T00:00:00+00:00",
            "move_from_recent_low_pct": 25.0,
            "paper_trade_created": False,
            "paper_trade_skip_reason": "Exhaustion risk is High.",
        },
        {
            # Below 20% — excluded entirely.
            "symbol": "SMALLUSDT",
            "alerted_at": "2026-08-03T00:00:00+00:00",
            "move_from_recent_low_pct": 5.0,
            "paper_trade_created": False,
        },
        {
            # Before the week cutoff — excluded entirely.
            "symbol": "OLDUSDT",
            "alerted_at": "2026-07-20T00:00:00+00:00",
            "move_from_recent_low_pct": 30.0,
            "paper_trade_created": False,
        },
    ]

    result = app_main._movers_over_20pct_this_week(alert_history, week_cutoff)

    assert result["total"] == 3
    assert result["traded"] == 1
    assert result["missed"] == 2
    assert result["missed_reason_counts"] == {"Exhaustion risk High": 2}
