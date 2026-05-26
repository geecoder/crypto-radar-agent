"""Strategy comparison reports for simulated paper trades.

This module analyzes paper-trading records only. It does not place orders,
does not use private exchange APIs, and does not provide live-trading access.
"""

SCORE_BANDS = (
    "0-39",
    "40-59",
    "60-69",
    "70-79",
    "80-89",
    "90-100",
)
GROUP_SECTIONS = (
    ("by_strategy_name", "Performance by Strategy"),
    ("by_alert_type", "Performance by Alert Type"),
    ("by_trade_plan_type", "Performance by Trade Plan Type"),
    ("by_continuation_target", "Performance by Continuation Target"),
    ("by_move_stage", "Performance by Move Stage"),
    ("by_liquidity_label", "Performance by Liquidity"),
    ("by_exhaustion_risk_level", "Performance by Exhaustion Risk"),
    ("by_score_band", "Performance by Score Band"),
)


def build_strategy_performance_report(paper_trades: list[dict]) -> dict:
    """Build a strategy-performance report from paper trades."""
    trades = [trade for trade in paper_trades if isinstance(trade, dict)]
    open_trades = [
        trade
        for trade in trades
        if str(trade.get("status", "")).lower() == "open"
    ]
    closed_trades = [trade for trade in trades if is_closed_trade(trade)]
    winning_trades = [trade for trade in closed_trades if is_winning_trade(trade)]
    losing_trades = [trade for trade in closed_trades if is_losing_trade(trade)]
    breakeven_trades = [
        trade
        for trade in closed_trades
        if _as_float(trade.get("pnl_pct")) == 0
    ]
    pnl_values = _pnl_values(closed_trades)
    pnl_amount_values = [
        pnl_amount
        for trade in closed_trades
        if (pnl_amount := _as_float(trade.get("pnl_amount"))) is not None
    ]

    report = {
        "total_trades": len(trades),
        "open_trades": len(open_trades),
        "closed_trades": len(closed_trades),
        "winning_trades": len(winning_trades),
        "losing_trades": len(losing_trades),
        "breakeven_trades": len(breakeven_trades),
        "win_rate_pct": percentage(len(winning_trades), len(closed_trades)),
        "average_pnl_pct": average(pnl_values),
        "total_pnl_amount": _round(sum(pnl_amount_values)),
        "best_trade": _ranked_trade(closed_trades, reverse=True),
        "worst_trade": _ranked_trade(closed_trades, reverse=False),
        "by_strategy_name": _build_group_metrics(
            group_trades_by_key(trades, "strategy_name")
        ),
        "by_alert_type": _build_group_metrics(
            group_trades_by_key(trades, "alert_type")
        ),
        "by_trade_plan_type": _build_group_metrics(
            group_trades_by_key(trades, "trade_plan_type")
        ),
        "by_continuation_target": _build_group_metrics(
            group_trades_by_key(trades, "continuation_target")
        ),
        "by_move_stage": _build_group_metrics(
            group_trades_by_key(trades, "move_stage")
        ),
        "by_liquidity_label": _build_group_metrics(
            group_trades_by_key(trades, "liquidity_label")
        ),
        "by_exhaustion_risk_level": _build_group_metrics(
            group_trades_by_key(trades, "exhaustion_risk_level")
        ),
        "by_score_band": _build_group_metrics(_group_trades_by_score_band(trades)),
    }
    report["tuning_recommendations"] = generate_tuning_recommendations(report)

    return report


def format_strategy_performance_report(report: dict) -> str:
    """Format a strategy-performance report as readable plain text."""
    lines = [
        "Crypto Radar Strategy Performance Report",
        "",
        "Overview",
        f"Total trades: {report.get('total_trades', 0)}",
        f"Open trades: {report.get('open_trades', 0)}",
        f"Closed trades: {report.get('closed_trades', 0)}",
        f"Winning trades: {report.get('winning_trades', 0)}",
        f"Losing trades: {report.get('losing_trades', 0)}",
        f"Breakeven trades: {report.get('breakeven_trades', 0)}",
        f"Win rate: {_format_pct(report.get('win_rate_pct', 0))}%",
        f"Average P/L: {_format_pct(report.get('average_pnl_pct', 0))}%",
        f"Total P/L amount: {_format_currency(report.get('total_pnl_amount', 0))}",
        f"Best trade: {_format_trade(report.get('best_trade'))}",
        f"Worst trade: {_format_trade(report.get('worst_trade'))}",
    ]

    for report_key, section_title in GROUP_SECTIONS:
        lines.extend(["", section_title])
        lines.extend(_format_group_metrics(report.get(report_key, {})))

    lines.extend(
        [
            "",
            "Tuning Recommendations",
            *_format_recommendations(report.get("tuning_recommendations", [])),
            "",
            "Notes",
            "- This report analyzes simulated paper trades only.",
            "- Open trades are counted but realised performance uses closed trades only.",
            "- Do not use this report as live-trading automation.",
        ]
    )

    return "\n".join(lines)


def generate_tuning_recommendations(report: dict) -> list[str]:
    """Generate practical tuning recommendations from report metrics."""
    recommendations = []
    closed_trades = int(report.get("closed_trades", 0) or 0)
    strategies = report.get("by_strategy_name", {})

    if closed_trades < 10:
        recommendations.append(
            "Sample size is still small. Avoid making major strategy changes yet."
        )

    for strategy_name, metrics in strategies.items():
        if (
            metrics.get("closed_count", 0) >= 5
            and metrics.get("win_rate_pct", 0) >= 55
            and metrics.get("average_pnl_pct", 0) > 0
        ):
            recommendations.append(
                f"Strategy {strategy_name} is showing early positive performance. Keep monitoring."
            )

        if (
            metrics.get("closed_count", 0) >= 5
            and metrics.get("win_rate_pct", 0) < 40
        ):
            recommendations.append(
                f"Strategy {strategy_name} is underperforming. Consider raising its entry threshold or disabling it temporarily."
            )

    liquidity_groups = report.get("by_liquidity_label", {})
    thin_metrics = liquidity_groups.get("Thin") or liquidity_groups.get("Very thin")

    if thin_metrics and thin_metrics.get("average_pnl_pct", 0) < 0:
        recommendations.append(
            "Thin liquidity setups are underperforming. Continue excluding or heavily penalising thin liquidity."
        )

    high_exhaustion = report.get("by_exhaustion_risk_level", {}).get("High")

    if high_exhaustion and high_exhaustion.get("average_pnl_pct", 0) < 0:
        recommendations.append(
            "High exhaustion setups are underperforming. Avoid creating paper trades for high exhaustion alerts."
        )

    parabolic_alerts = report.get("by_alert_type", {}).get("Parabolic Watch Alert")

    if parabolic_alerts and parabolic_alerts.get("count", 0) > 0:
        recommendations.append(
            "Parabolic Watch Alerts are high-risk paper-only experiments; keep them separate from clean continuation strategies."
        )

    score_bands = report.get("by_score_band", {})
    band_60_69 = score_bands.get("60-69", {})
    band_70_79 = score_bands.get("70-79", {})

    if (
        band_60_69.get("closed_count", 0) > 0
        and band_70_79.get("closed_count", 0) > 0
        and band_60_69.get("average_pnl_pct", 0) < 0
        and band_70_79.get("average_pnl_pct", 0)
        > band_60_69.get("average_pnl_pct", 0)
    ):
        recommendations.append(
            "Consider raising alert/paper trade threshold from 65 to 70."
        )

    if not _has_enough_group_data(report):
        recommendations.append(
            "More paper-trade data is needed before tuning thresholds."
        )

    return _dedupe(recommendations)


def is_closed_trade(trade: dict) -> bool:
    """Return whether a trade is closed."""
    return str(trade.get("status", "")).lower() == "closed"


def is_winning_trade(trade: dict) -> bool:
    """Return whether a closed trade is profitable."""
    pnl_pct = _as_float(trade.get("pnl_pct"))
    return is_closed_trade(trade) and pnl_pct is not None and pnl_pct > 0


def is_losing_trade(trade: dict) -> bool:
    """Return whether a closed trade is losing."""
    pnl_pct = _as_float(trade.get("pnl_pct"))
    return is_closed_trade(trade) and pnl_pct is not None and pnl_pct < 0


def percentage(numerator: int, denominator: int) -> float:
    """Return a rounded percentage."""
    if denominator == 0:
        return 0.0

    return _round((numerator / denominator) * 100)


def average(values: list[float]) -> float:
    """Return a rounded average."""
    numeric_values = [
        value
        for value in (_as_float(value) for value in values)
        if value is not None
    ]

    if not numeric_values:
        return 0.0

    return _round(sum(numeric_values) / len(numeric_values))


def get_score_band(score: int | float | None) -> str:
    """Return a score band for an opportunity score."""
    numeric_score = _as_float(score)

    if numeric_score is None:
        return "Unknown"

    if numeric_score < 40:
        return "0-39"
    if numeric_score < 60:
        return "40-59"
    if numeric_score < 70:
        return "60-69"
    if numeric_score < 80:
        return "70-79"
    if numeric_score < 90:
        return "80-89"
    return "90-100"


def group_trades_by_key(trades: list[dict], key: str) -> dict:
    """Group trades by a key, using Unknown for missing values."""
    grouped: dict[str, list[dict]] = {}

    for trade in trades:
        if not isinstance(trade, dict):
            continue

        group = str(trade.get(key) or "Unknown")
        grouped.setdefault(group, []).append(trade)

    return dict(sorted(grouped.items()))


def _build_group_metrics(grouped_trades: dict[str, list[dict]]) -> dict:
    """Build standard realised-performance metrics for each group."""
    return {
        group: _metrics_for_trades(trades)
        for group, trades in grouped_trades.items()
    }


def _metrics_for_trades(trades: list[dict]) -> dict:
    """Build standard metrics for a list of trades."""
    closed_trades = [trade for trade in trades if is_closed_trade(trade)]
    winning_trades = [trade for trade in closed_trades if is_winning_trade(trade)]
    losing_trades = [trade for trade in closed_trades if is_losing_trade(trade)]
    pnl_values = _pnl_values(closed_trades)
    pnl_amount_values = [
        pnl_amount
        for trade in closed_trades
        if (pnl_amount := _as_float(trade.get("pnl_amount"))) is not None
    ]

    return {
        "count": len(trades),
        "closed_count": len(closed_trades),
        "win_rate_pct": percentage(len(winning_trades), len(closed_trades)),
        "average_pnl_pct": average(pnl_values),
        "total_pnl_amount": _round(sum(pnl_amount_values)),
        "average_win_pct": average(_pnl_values(winning_trades)),
        "average_loss_pct": average(_pnl_values(losing_trades)),
        "best_pnl_pct": _best_pnl(pnl_values),
        "worst_pnl_pct": _worst_pnl(pnl_values),
    }


def _group_trades_by_score_band(trades: list[dict]) -> dict:
    """Group trades by opportunity score band."""
    grouped: dict[str, list[dict]] = {band: [] for band in SCORE_BANDS}

    for trade in trades:
        if not isinstance(trade, dict):
            continue

        grouped.setdefault(
            get_score_band(trade.get("opportunity_score")),
            [],
        ).append(trade)

    return {
        group: group_trades
        for group, group_trades in grouped.items()
        if group_trades
    }


def _ranked_trade(trades: list[dict], reverse: bool) -> dict | None:
    """Return best or worst closed trade by pnl_pct."""
    ranked = [
        _trade_summary(trade, pnl_pct)
        for trade in trades
        if (pnl_pct := _as_float(trade.get("pnl_pct"))) is not None
    ]

    if not ranked:
        return None

    return sorted(ranked, key=lambda trade: trade["pnl_pct"], reverse=reverse)[0]


def _trade_summary(trade: dict, pnl_pct: float) -> dict:
    """Return compact trade details for rankings."""
    return {
        "id": trade.get("id"),
        "symbol": trade.get("symbol") or "Unknown",
        "strategy_name": trade.get("strategy_name") or "Unknown",
        "alert_type": trade.get("alert_type") or "Unknown",
        "pnl_pct": _round(pnl_pct),
        "pnl_amount": _round(_as_float(trade.get("pnl_amount")) or 0.0),
        "exit_reason": trade.get("exit_reason") or "Unknown",
    }


def _pnl_values(trades: list[dict]) -> list[float]:
    """Return numeric pnl_pct values from trades."""
    return [
        pnl_pct
        for trade in trades
        if (pnl_pct := _as_float(trade.get("pnl_pct"))) is not None
    ]


def _best_pnl(values: list[float]) -> float:
    """Return best P/L percentage from values."""
    if not values:
        return 0.0

    return _round(max(values))


def _worst_pnl(values: list[float]) -> float:
    """Return worst P/L percentage from values."""
    if not values:
        return 0.0

    return _round(min(values))


def _has_enough_group_data(report: dict) -> bool:
    """Return whether any group has enough closed trades for tuning."""
    for report_key, _section_title in GROUP_SECTIONS:
        for metrics in report.get(report_key, {}).values():
            if metrics.get("closed_count", 0) >= 5:
                return True

    return False


def _dedupe(items: list[str]) -> list[str]:
    """Deduplicate recommendations while preserving order."""
    seen = set()
    deduped = []

    for item in items:
        if item in seen:
            continue

        seen.add(item)
        deduped.append(item)

    return deduped


def _as_float(value) -> float | None:
    """Convert a value to float when possible."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: float) -> float:
    """Round report values consistently."""
    return round(value, 2)


def _format_group_metrics(group_metrics: dict) -> list[str]:
    """Format group metrics into readable lines."""
    if not group_metrics:
        return ["- Not available"]

    return [
        (
            f"- {group}: count {metrics.get('count', 0)}, "
            f"closed {metrics.get('closed_count', 0)}, "
            f"win {_format_pct(metrics.get('win_rate_pct', 0))}%, "
            f"avg P/L {_format_pct(metrics.get('average_pnl_pct', 0))}%, "
            f"total {_format_currency(metrics.get('total_pnl_amount', 0))}, "
            f"avg win {_format_pct(metrics.get('average_win_pct', 0))}%, "
            f"avg loss {_format_pct(metrics.get('average_loss_pct', 0))}%, "
            f"best {_format_pct(metrics.get('best_pnl_pct', 0))}%, "
            f"worst {_format_pct(metrics.get('worst_pnl_pct', 0))}%"
        )
        for group, metrics in group_metrics.items()
    ]


def _format_recommendations(recommendations: list[str]) -> list[str]:
    """Format recommendation lines."""
    if not recommendations:
        return ["- No recommendations available yet."]

    return [f"- {recommendation}" for recommendation in recommendations]


def _format_trade(trade: dict | None) -> str:
    """Format a ranked trade."""
    if not trade:
        return "Not available"

    return (
        f"{trade.get('symbol', 'Unknown')} "
        f"({_format_pct(trade.get('pnl_pct', 0))}%, "
        f"{_format_currency(trade.get('pnl_amount', 0))}, "
        f"{trade.get('alert_type', 'Unknown')})"
    )


def _format_pct(value) -> str:
    """Format a numeric percentage without noisy trailing zeros."""
    number = _as_float(value) or 0.0
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _format_currency(value) -> str:
    """Format a numeric P/L amount."""
    number = _as_float(value) or 0.0
    sign = "-" if number < 0 else ""
    return f"{sign}${abs(number):.2f}"
