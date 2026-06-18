"""Tests for the Binance executor and go-live precondition gates."""

from app.exchange.binance_executor import (
    GoLiveGate,
    all_go_live_gates_pass,
    check_go_live_preconditions,
    format_go_live_report,
)


def _gates(
    closed=100, win_rate=60.0, avg_pnl=2.5, tg_rate=95.0, risk=True
) -> list[GoLiveGate]:
    return check_go_live_preconditions(
        closed_paper_trade_count=closed,
        win_rate_last_100=win_rate,
        avg_pnl_last_100=avg_pnl,
        telegram_send_rate_7d=tg_rate,
        risk_manager_active=risk,
    )


def test_all_gates_pass_when_criteria_met() -> None:
    gates = _gates()
    assert all_go_live_gates_pass(gates) is True


def test_fails_when_not_enough_paper_trades() -> None:
    gates = _gates(closed=99)
    assert all_go_live_gates_pass(gates) is False
    failing = [g for g in gates if not g.passed]
    assert any(g.name == "min_paper_trades" for g in failing)


def test_fails_when_win_rate_too_low() -> None:
    gates = _gates(win_rate=54.9)
    assert all_go_live_gates_pass(gates) is False
    failing = [g for g in gates if not g.passed]
    assert any(g.name == "min_win_rate" for g in failing)


def test_fails_when_avg_pnl_negative() -> None:
    gates = _gates(avg_pnl=-0.1)
    assert all_go_live_gates_pass(gates) is False
    failing = [g for g in gates if not g.passed]
    assert any(g.name == "positive_avg_pnl" for g in failing)


def test_fails_when_telegram_rate_low() -> None:
    gates = _gates(tg_rate=89.9)
    assert all_go_live_gates_pass(gates) is False
    failing = [g for g in gates if not g.passed]
    assert any(g.name == "telegram_send_rate" for g in failing)


def test_fails_when_risk_manager_not_active() -> None:
    gates = _gates(risk=False)
    assert all_go_live_gates_pass(gates) is False
    failing = [g for g in gates if not g.passed]
    assert any(g.name == "risk_manager_active" for g in failing)


def test_format_go_live_report_shows_pass_fail() -> None:
    gates = _gates(closed=50, win_rate=40.0)  # two failures
    report = format_go_live_report(gates)
    assert "PASS" in report
    assert "FAIL" in report
    assert "NOT READY" in report


def test_format_go_live_report_shows_ready_when_all_pass() -> None:
    gates = _gates()
    report = format_go_live_report(gates)
    assert "READY" in report
    assert "NOT READY" not in report
