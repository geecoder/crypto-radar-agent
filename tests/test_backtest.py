"""Tests for the honest 60-day backtest of the reconciled Block 1-4 logic."""

from datetime import datetime, timedelta, timezone

from app.analysis import backtest


def _alert_row(**overrides) -> dict:
    row = {
        "symbol": "HEIUSDT",
        "alerted_at": datetime(2026, 6, 1, tzinfo=timezone.utc),
        "latest_close": 0.20,
        "alert_type": "Parabolic Watch Alert",
        "opportunity_score": 58,
        "move_from_recent_low_pct": 116.5,
        "liquidity_label": "Good",
        "exhaustion_risk_level": "Medium",
        "recent_price_changes": {
            "change_1h_pct": 2.5,
            "change_2h_pct": 5.5,
            "change_4h_pct": 11.0,
            "change_24h_pct": 75.0,
        },
        "volume_acceleration": {
            "volume_acceleration_1h_ratio": 1.4,
            "volume_acceleration_2h_ratio": 2.1,
        },
        "breakout_signal": {"score": 60},
        "trend_signal": {"score": 60},
        "volatility_signal": {"score": 60},
        "paper_trade_created": False,
    }
    row.update(overrides)
    return row


def _flat_klines(open_time_ms: int, hours: int, close: float = 0.20) -> list:
    """Return flat candles (no TP/SL hit) so max_hold_expired closes the trade."""
    rows = []
    for i in range(hours * 4 + 1):  # 15m candles
        candle_time = open_time_ms + i * 15 * 60 * 1000
        rows.append(
            [
                candle_time,
                str(close),
                str(close),
                str(close),
                str(close),
                "10",
                candle_time + 15 * 60 * 1000,
            ]
        )
    return rows


def test_classify_under_new_rules_parabolic_move() -> None:
    row = _alert_row(move_from_recent_low_pct=214.0, liquidity_label="Good")

    assert backtest.classify_under_new_rules(row) == "Parabolic Watch Alert"


def test_classify_under_new_rules_falls_back_to_continuation() -> None:
    row = _alert_row(
        move_from_recent_low_pct=25.0,
        recent_price_changes={
            "change_1h_pct": 1.0,
            "change_2h_pct": 1.0,
            "change_4h_pct": 1.0,
            "change_24h_pct": 5.0,
        },
        opportunity_score=70,
    )

    # 25% move is above Active Breakout's narrowed 10-20% window -> falls
    # through to the score-based Continuation Alert fallback.
    assert backtest.classify_under_new_rules(row) == "Continuation Alert"


def test_classify_under_new_rules_no_alert_when_score_too_low() -> None:
    row = _alert_row(
        move_from_recent_low_pct=25.0,
        recent_price_changes={
            "change_1h_pct": 1.0,
            "change_2h_pct": 1.0,
            "change_4h_pct": 1.0,
            "change_24h_pct": 5.0,
        },
        opportunity_score=40,
    )

    assert backtest.classify_under_new_rules(row) == "No Alert"


def test_evaluate_new_eligibility_parabolic_move_above_150_pct_now_eligible() -> None:
    # This is the HEIUSDT fix: >150% move used to be hard-rejected.
    row = _alert_row(move_from_recent_low_pct=214.0, opportunity_score=58)

    eligible, reason, strategy = backtest.evaluate_new_eligibility(
        row, "Parabolic Watch Alert"
    )

    assert eligible is True
    assert strategy.name == "parabolic_continuation_paper"


def test_evaluate_new_eligibility_rejects_low_24h_change() -> None:
    row = _alert_row(
        move_from_recent_low_pct=214.0,
        recent_price_changes={
            "change_1h_pct": 2.5,
            "change_2h_pct": 5.5,
            "change_4h_pct": 11.0,
            "change_24h_pct": 30.0,
        },
    )

    eligible, reason, _strategy = backtest.evaluate_new_eligibility(
        row, "Parabolic Watch Alert"
    )

    assert eligible is False
    assert "24h change is below 50%" in reason


def test_estimate_conviction_position_size_scales_with_score_and_liquidity() -> None:
    from app.trading.strategy_config import get_default_paper_trading_strategy

    strategy = get_default_paper_trading_strategy()
    high = _alert_row(opportunity_score=100, liquidity_label="Excellent")
    low = _alert_row(opportunity_score=0, liquidity_label="Very thin")

    high_size, high_slip = backtest.estimate_conviction_position_size(high, strategy)
    low_size, low_slip = backtest.estimate_conviction_position_size(low, strategy)

    assert high_size > low_size
    assert high_slip < low_slip


def test_backtest_alert_full_flow_with_stub_klines() -> None:
    row = _alert_row()
    alerted_at_ms = int(row["alerted_at"].timestamp() * 1000)

    def fake_klines_fetcher(symbol, start_time_ms, max_hold_hours):
        assert symbol == "HEIUSDT"
        assert start_time_ms == alerted_at_ms
        return _flat_klines(start_time_ms, max_hold_hours, close=0.20)

    outcome = backtest.backtest_alert(row, fake_klines_fetcher)

    assert outcome["new_alert_type"] == "Parabolic Watch Alert"
    assert outcome["would_trade"] is True
    assert outcome["exit_reason"] == "max_hold_expired"
    assert outcome["gross_pnl_pct"] == 0.0
    assert outcome["net_pnl_pct"] is not None
    assert outcome["position_size_usd"] > 0


def test_backtest_alert_ineligible_never_calls_klines_fetcher() -> None:
    row = _alert_row(
        move_from_recent_low_pct=214.0,
        recent_price_changes={
            "change_1h_pct": 1.0,
            "change_2h_pct": 1.0,
            "change_4h_pct": 1.0,
            "change_24h_pct": 10.0,
        },
    )
    calls = []

    def fake_klines_fetcher(symbol, start_time_ms, max_hold_hours):
        calls.append(symbol)
        return []

    outcome = backtest.backtest_alert(row, fake_klines_fetcher)

    assert outcome["would_trade"] is False
    assert calls == []


def test_run_backtest_aggregates_by_strategy() -> None:
    parabolic_row = _alert_row()
    continuation_row = _alert_row(
        symbol="ETHUSDT",
        alert_type="Continuation Alert",
        move_from_recent_low_pct=8.0,
        opportunity_score=70,
        recent_price_changes={
            "change_1h_pct": 1.0,
            "change_2h_pct": 1.0,
            "change_4h_pct": 1.0,
            "change_24h_pct": 5.0,
        },
    )

    def fake_klines_fetcher(symbol, start_time_ms, max_hold_hours):
        return _flat_klines(start_time_ms, max_hold_hours, close=0.20 if symbol == "HEIUSDT" else 100.0)

    # Give continuation_row a plausible entry price matching the flat klines.
    continuation_row["latest_close"] = 100.0

    report = backtest.run_backtest([parabolic_row, continuation_row], fake_klines_fetcher)

    assert report["total_alerts_replayed"] == 2
    assert report["new_logic_would_trade_count"] == 2
    assert set(report["by_strategy"].keys()) == {
        "parabolic_continuation_paper",
        "default_momentum_continuation",
    }
    assert "approximation_note" in report
    assert "format" not in report  # sanity: report is data, not pre-formatted


def test_format_backtest_report_produces_readable_text() -> None:
    report = {
        "approximation_note": "note",
        "total_alerts_replayed": 10,
        "new_logic_would_trade_count": 3,
        "actual_historical_trade_count": 1,
        "overall": {"count": 3, "win_rate": 66.7, "avg_net_pnl_pct": 1.5},
        "by_strategy": {
            "parabolic_continuation_paper": {
                "count": 3,
                "win_rate": 66.7,
                "avg_net_pnl_pct": 1.5,
            }
        },
    }

    text = backtest.format_backtest_report(report)

    assert "60-Day Backtest" in text
    assert "NOTE: note" in text
    assert "Alerts replayed: 10" in text
    assert "parabolic_continuation_paper: 3 trades" in text
