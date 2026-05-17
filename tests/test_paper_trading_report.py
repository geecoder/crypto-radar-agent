"""Tests for paper trading performance reports."""

from app.analysis.paper_trading_report import (
    build_paper_trading_report,
    format_paper_trading_report,
)


def _closed_trade(
    symbol: str,
    pnl_pct: float,
    pnl_amount: float,
    exit_reason: str,
    target_bucket: str = "+20% momentum setup",
    continuation_target: str = "+20% continuation watch",
    move_stage: str = "Stage 3 - Confirmed early momentum",
    liquidity_label: str = "Strong",
    exhaustion_risk_level: str = "Medium",
) -> dict:
    return {
        "id": f"paper_{symbol}_{exit_reason}_{pnl_pct}",
        "symbol": symbol,
        "status": "closed",
        "pnl_pct": pnl_pct,
        "pnl_amount": pnl_amount,
        "exit_reason": exit_reason,
        "target_bucket": target_bucket,
        "continuation_target": continuation_target,
        "move_stage": move_stage,
        "liquidity_label": liquidity_label,
        "exhaustion_risk_level": exhaustion_risk_level,
    }


def test_build_paper_trading_report_empty_trades() -> None:
    report = build_paper_trading_report([])
    formatted = format_paper_trading_report(report)

    assert report["total_trades"] == 0
    assert report["open_trades"] == 0
    assert report["closed_trades"] == 0
    assert report["win_rate_pct"] == 0.0
    assert report["best_trade"] is None
    assert "No paper trades available yet" in formatted
    assert "No closed paper trades yet" in formatted


def test_open_trades_ignored_in_realised_pnl() -> None:
    trades = [
        {
            "id": "paper_open",
            "symbol": "BTCUSDT",
            "status": "open",
            "pnl_pct": 99,
            "pnl_amount": 99,
        },
        _closed_trade("ETHUSDT", 10, 10, "take_profit_1"),
    ]

    report = build_paper_trading_report(trades)

    assert report["total_trades"] == 2
    assert report["open_trades"] == 1
    assert report["closed_trades"] == 1
    assert report["total_pnl_amount"] == 10
    assert report["total_pnl_pct_sum"] == 10
    assert report["average_pnl_pct"] == 10


def test_win_loss_breakeven_calculations() -> None:
    report = build_paper_trading_report(
        [
            _closed_trade("BTCUSDT", 8, 8, "take_profit_1"),
            _closed_trade("ETHUSDT", -5, -5, "stop_loss"),
            _closed_trade("SOLUSDT", 0, 0, "max_hold_expired"),
        ]
    )

    assert report["winning_trades"] == 1
    assert report["losing_trades"] == 1
    assert report["breakeven_trades"] == 1
    assert report["win_rate_pct"] == 33.33
    assert report["loss_rate_pct"] == 33.33
    assert report["average_win_pct"] == 8
    assert report["average_loss_pct"] == -5
    assert report["average_pnl_pct"] == 1


def test_exit_reason_counts() -> None:
    report = build_paper_trading_report(
        [
            _closed_trade("BTCUSDT", 8, 8, "take_profit_1"),
            _closed_trade("ETHUSDT", 15, 15, "take_profit_1"),
            _closed_trade("SOLUSDT", -5, -5, "stop_loss"),
        ]
    )

    assert report["exit_reason_counts"] == {
        "stop_loss": 1,
        "take_profit_1": 2,
    }


def test_best_and_worst_trade_selection() -> None:
    report = build_paper_trading_report(
        [
            _closed_trade("BTCUSDT", 8, 8, "take_profit_1"),
            _closed_trade("ETHUSDT", 20, 20, "take_profit_3"),
            _closed_trade("SOLUSDT", -5, -5, "stop_loss"),
        ]
    )

    assert report["best_trade"]["symbol"] == "ETHUSDT"
    assert report["best_trade"]["pnl_pct"] == 20
    assert report["worst_trade"]["symbol"] == "SOLUSDT"
    assert report["worst_trade"]["pnl_pct"] == -5
    assert report["best_symbol"]["symbol"] == "ETHUSDT"
    assert report["worst_symbol"]["symbol"] == "SOLUSDT"


def test_grouped_average_calculations() -> None:
    report = build_paper_trading_report(
        [
            _closed_trade(
                "BTCUSDT",
                8,
                8,
                "take_profit_1",
                target_bucket="+20% setup",
                continuation_target="+20% continuation watch",
                move_stage="Stage 2",
                liquidity_label="Strong",
                exhaustion_risk_level="Low",
            ),
            _closed_trade(
                "ETHUSDT",
                12,
                12,
                "take_profit_2",
                target_bucket="+20% setup",
                continuation_target="+20% continuation watch",
                move_stage="Stage 2",
                liquidity_label="Strong",
                exhaustion_risk_level="Low",
            ),
            _closed_trade(
                "SOLUSDT",
                -5,
                -5,
                "stop_loss",
                target_bucket="+50% setup",
                continuation_target="+50% high-volatility watch",
                move_stage="Stage 4",
                liquidity_label="Good",
                exhaustion_risk_level="Medium",
            ),
        ]
    )

    assert report["average_pnl_by_exit_reason"]["take_profit_1"] == 8
    assert report["average_pnl_by_target_bucket"]["+20% setup"] == 10
    assert report["average_pnl_by_continuation_target"][
        "+20% continuation watch"
    ] == 10
    assert report["average_pnl_by_move_stage"]["Stage 2"] == 10
    assert report["average_pnl_by_liquidity_label"]["Strong"] == 10
    assert report["average_pnl_by_exhaustion_risk_level"]["Low"] == 10
