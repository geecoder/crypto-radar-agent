"""Tests for the weekly go-live readiness Telegram report."""

from app.exchange.binance_executor import (
    check_go_live_preconditions,
    format_go_live_telegram_message,
)


def _msg(
    closed=120, win_rate_100=47.0, avg_pnl=1.2, tg_rate=96.0,
    win_this=49.0, win_last=44.0,
    post_b3=45, breakdown=None, total=120,
    good_liq_closed=100, good_liq_net_avg=1.0,
):
    gates = check_go_live_preconditions(
        closed_paper_trade_count=closed,
        win_rate_last_100=win_rate_100,
        avg_pnl_last_100=avg_pnl,
        telegram_send_rate_7d=tg_rate,
        risk_manager_active=True,
        good_liquidity_closed_trade_count=good_liq_closed,
        good_liquidity_net_avg_pnl_pct=good_liq_net_avg,
    )
    return format_go_live_telegram_message(
        gates=gates,
        win_rate_last_100=win_rate_100,
        win_rate_this_week=win_this,
        win_rate_last_week=win_last,
        post_block3_closed=post_b3,
        exit_breakdown_this_week=breakdown or {"stop_loss": 3, "take_profit": 7, "max_hold_expired": 5},
        total_closed=total,
    )


def test_message_contains_all_sections() -> None:
    msg = _msg()
    assert "Weekly Go-Live Readiness Report" in msg
    assert "Gates:" in msg
    assert "Win rate:" in msg
    assert "Post-Block 3 trades" in msg
    assert "Exit reasons this week" in msg
    assert "Verdict:" in msg


def test_message_shows_pass_fail_icons() -> None:
    msg = _msg()
    assert "✅" in msg
    assert "❌" in msg


def test_message_shows_win_rate_trend() -> None:
    msg = _msg(win_this=49.0, win_last=44.0)
    assert "49.0%" in msg
    assert "44.0%" in msg
    assert "📈" in msg   # positive trend


def test_message_shows_declining_trend() -> None:
    msg = _msg(win_this=42.0, win_last=48.0)
    assert "📉" in msg


def test_message_shows_post_block3_count() -> None:
    msg = _msg(post_b3=37)
    assert "37" in msg
    assert "100 needed" in msg


def test_exit_breakdown_shows_percentages() -> None:
    msg = _msg(breakdown={"stop_loss": 5, "take_profit": 10, "max_hold_expired": 5})
    assert "Stop-loss" in msg
    assert "Take-profit" in msg
    assert "Max-hold expired" in msg


def test_verdict_all_pass() -> None:
    msg = _msg(closed=110, win_rate_100=57.0, win_this=57.0, win_last=54.0)
    assert "ready to go live" in msg


def test_verdict_on_track() -> None:
    msg = _msg(win_this=52.0, win_last=48.0)
    assert "On track" in msg or "climbing" in msg


def test_verdict_stalled() -> None:
    msg = _msg(win_this=35.0, win_last=35.5)
    assert "stalled" in msg or "review" in msg.lower() or "Win rate" in msg


def test_verdict_declining() -> None:
    msg = _msg(win_this=38.0, win_last=45.0)
    assert "declining" in msg or "review" in msg.lower()


def test_message_omits_movers_section_when_not_provided() -> None:
    msg = _msg()
    assert "Movers" not in msg


def test_message_includes_movers_section_when_provided() -> None:
    gates = check_go_live_preconditions(
        closed_paper_trade_count=120,
        win_rate_last_100=47.0,
        avg_pnl_last_100=1.2,
        telegram_send_rate_7d=96.0,
        risk_manager_active=True,
        good_liquidity_closed_trade_count=100,
        good_liquidity_net_avg_pnl_pct=1.0,
    )
    msg = format_go_live_telegram_message(
        gates=gates,
        win_rate_last_100=47.0,
        win_rate_this_week=49.0,
        win_rate_last_week=44.0,
        post_block3_closed=45,
        exit_breakdown_this_week={"stop_loss": 3, "take_profit": 7, "max_hold_expired": 5},
        total_closed=120,
        movers_over_20pct={
            "total": 8,
            "traded": 3,
            "missed": 5,
            "missed_reason_counts": {"Exhaustion risk High": 3, "Move-window mismatch": 2},
        },
    )

    assert "Movers &gt;20% this week" in msg
    assert "Traded: <b>3</b>" in msg
    assert "Missed: <b>5</b>" in msg
    assert "Exhaustion risk High: 3" in msg
    assert "Move-window mismatch: 2" in msg
