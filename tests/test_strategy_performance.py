"""Tests for strategy performance comparison reports."""

from app.analysis.strategy_performance import (
    average,
    build_strategy_performance_report,
    format_strategy_performance_report,
    generate_tuning_recommendations,
    get_score_band,
    group_trades_by_key,
    is_closed_trade,
    is_losing_trade,
    is_winning_trade,
    percentage,
)


def _trade(
    symbol: str,
    status: str = "closed",
    pnl_pct: float = 8,
    pnl_amount: float = 8,
    strategy_name: str = "default_momentum_continuation",
    alert_type: str = "Continuation Alert",
    trade_plan_type: str = "standard_continuation",
    continuation_target: str = "+20% continuation watch",
    move_stage: str = "Stage 3 - Confirmed early momentum",
    liquidity_label: str = "Strong",
    exhaustion_risk_level: str = "Medium",
    opportunity_score: float = 72,
) -> dict:
    return {
        "id": f"paper_{symbol}_{pnl_pct}",
        "symbol": symbol,
        "status": status,
        "pnl_pct": pnl_pct,
        "pnl_amount": pnl_amount,
        "strategy_name": strategy_name,
        "alert_type": alert_type,
        "trade_plan_type": trade_plan_type,
        "continuation_target": continuation_target,
        "move_stage": move_stage,
        "liquidity_label": liquidity_label,
        "exhaustion_risk_level": exhaustion_risk_level,
        "opportunity_score": opportunity_score,
        "exit_reason": "take_profit_1" if pnl_pct > 0 else "stop_loss",
    }


def test_helpers_handle_basic_trade_math() -> None:
    win = _trade("BTCUSDT", pnl_pct=8)
    loss = _trade("ETHUSDT", pnl_pct=-5)
    open_trade = _trade("SOLUSDT", status="open")

    assert is_closed_trade(win) is True
    assert is_closed_trade(open_trade) is False
    assert is_winning_trade(win) is True
    assert is_winning_trade(loss) is False
    assert is_losing_trade(loss) is True
    assert percentage(1, 4) == 25
    assert percentage(1, 0) == 0
    assert average([1, 2, 3]) == 2
    assert average([]) == 0


def test_score_band_grouping() -> None:
    assert get_score_band(None) == "Unknown"
    assert get_score_band(39) == "0-39"
    assert get_score_band(40) == "40-59"
    assert get_score_band(60) == "60-69"
    assert get_score_band(70) == "70-79"
    assert get_score_band(80) == "80-89"
    assert get_score_band(90) == "90-100"


def test_group_trades_by_key_uses_unknown_for_missing_values() -> None:
    grouped = group_trades_by_key(
        [
            _trade("BTCUSDT", strategy_name="default"),
            {"symbol": "BADUSDT"},
        ],
        "strategy_name",
    )

    assert list(grouped) == ["Unknown", "default"]
    assert grouped["Unknown"][0]["symbol"] == "BADUSDT"


def test_build_strategy_performance_report_empty_trades() -> None:
    report = build_strategy_performance_report([])

    assert report["total_trades"] == 0
    assert report["open_trades"] == 0
    assert report["closed_trades"] == 0
    assert report["win_rate_pct"] == 0
    assert report["average_pnl_pct"] == 0
    assert report["best_trade"] is None
    assert report["worst_trade"] is None
    assert "More paper-trade data is needed" in " ".join(
        report["tuning_recommendations"]
    )


def test_build_strategy_performance_report_only_open_trades() -> None:
    report = build_strategy_performance_report(
        [_trade("BTCUSDT", status="open", pnl_pct=99, pnl_amount=99)]
    )

    assert report["total_trades"] == 1
    assert report["open_trades"] == 1
    assert report["closed_trades"] == 0
    assert report["average_pnl_pct"] == 0
    assert report["total_pnl_amount"] == 0


def test_win_loss_and_group_calculations() -> None:
    report = build_strategy_performance_report(
        [
            _trade("BTCUSDT", pnl_pct=8, pnl_amount=8),
            _trade("ETHUSDT", pnl_pct=-5, pnl_amount=-5),
            _trade("SOLUSDT", pnl_pct=0, pnl_amount=0),
        ]
    )

    assert report["closed_trades"] == 3
    assert report["winning_trades"] == 1
    assert report["losing_trades"] == 1
    assert report["breakeven_trades"] == 1
    assert report["win_rate_pct"] == 33.33
    assert report["average_pnl_pct"] == 1
    assert report["total_pnl_amount"] == 3
    assert report["best_trade"]["symbol"] == "BTCUSDT"
    assert report["worst_trade"]["symbol"] == "ETHUSDT"


def test_grouping_by_strategy_alert_type_and_score_band() -> None:
    report = build_strategy_performance_report(
        [
            _trade(
                "BTCUSDT",
                strategy_name="default",
                alert_type="Continuation Alert",
                opportunity_score=65,
                pnl_pct=8,
            ),
            _trade(
                "ETHUSDT",
                strategy_name="aggressive",
                alert_type="Active Breakout Alert",
                opportunity_score=75,
                pnl_pct=-5,
            ),
        ]
    )

    assert report["by_strategy_name"]["default"]["closed_count"] == 1
    assert report["by_strategy_name"]["aggressive"]["average_pnl_pct"] == -5
    assert report["by_alert_type"]["Continuation Alert"]["average_pnl_pct"] == 8
    assert report["by_alert_type"]["Active Breakout Alert"]["average_pnl_pct"] == -5
    assert report["by_score_band"]["60-69"]["closed_count"] == 1
    assert report["by_score_band"]["70-79"]["closed_count"] == 1


def test_tuning_recommendation_for_small_sample() -> None:
    report = build_strategy_performance_report([_trade("BTCUSDT")])

    assert (
        "Sample size is still small. Avoid making major strategy changes yet."
        in report["tuning_recommendations"]
    )


def test_tuning_recommendation_for_underperforming_strategy() -> None:
    trades = [
        _trade(f"BAD{index}USDT", pnl_pct=-5, pnl_amount=-5, strategy_name="weak")
        for index in range(5)
    ]
    report = build_strategy_performance_report(trades)

    assert (
        "Strategy weak is underperforming. Consider raising its entry threshold or disabling it temporarily."
        in report["tuning_recommendations"]
    )


def test_tuning_recommendation_for_positive_strategy() -> None:
    trades = [
        _trade(f"GOOD{index}USDT", pnl_pct=8, pnl_amount=8, strategy_name="good")
        for index in range(5)
    ]
    report = build_strategy_performance_report(trades)

    assert (
        "Strategy good is showing early positive performance. Keep monitoring."
        in report["tuning_recommendations"]
    )


def test_tuning_recommendations_for_risky_groups_and_thresholds() -> None:
    trades = [
        _trade("THINUSDT", pnl_pct=-5, liquidity_label="Thin", opportunity_score=65),
        _trade(
            "HIGHUSDT",
            pnl_pct=-4,
            exhaustion_risk_level="High",
            opportunity_score=65,
        ),
        _trade(
            "PARAUSDT",
            pnl_pct=1,
            alert_type="Parabolic Watch Alert",
            opportunity_score=65,
        ),
        _trade("GOODUSDT", pnl_pct=8, opportunity_score=75),
    ]
    report = build_strategy_performance_report(trades)
    recommendations = report["tuning_recommendations"]

    assert (
        "Thin liquidity setups are underperforming. Continue excluding or heavily penalising thin liquidity."
        in recommendations
    )
    assert (
        "High exhaustion setups are underperforming. Avoid creating paper trades for high exhaustion alerts."
        in recommendations
    )
    assert (
        "Parabolic Watch Alerts are high-risk paper-only experiments; keep them separate from clean continuation strategies."
        in recommendations
    )
    assert "Consider raising alert/paper trade threshold from 65 to 70." in recommendations


def test_generate_tuning_recommendations_more_data_when_no_large_groups() -> None:
    recommendations = generate_tuning_recommendations(
        {
            "closed_trades": 10,
            "by_strategy_name": {"default": {"closed_count": 2}},
            "by_alert_type": {},
            "by_trade_plan_type": {},
            "by_continuation_target": {},
            "by_move_stage": {},
            "by_liquidity_label": {},
            "by_exhaustion_risk_level": {},
            "by_score_band": {},
        }
    )

    assert "More paper-trade data is needed before tuning thresholds." in recommendations


def test_format_strategy_performance_report_contains_major_sections() -> None:
    report = build_strategy_performance_report([_trade("BTCUSDT")])
    formatted = format_strategy_performance_report(report)

    assert "Crypto Radar Strategy Performance Report" in formatted
    assert "Overview" in formatted
    assert "Performance by Strategy" in formatted
    assert "Performance by Alert Type" in formatted
    assert "Performance by Trade Plan Type" in formatted
    assert "Performance by Continuation Target" in formatted
    assert "Performance by Move Stage" in formatted
    assert "Performance by Liquidity" in formatted
    assert "Performance by Exhaustion Risk" in formatted
    assert "Performance by Score Band" in formatted
    assert "Tuning Recommendations" in formatted
    assert "Notes" in formatted
