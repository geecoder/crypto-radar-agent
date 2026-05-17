"""Performance reporting for simulated paper trades."""

GROUP_FIELDS = (
    "exit_reason",
    "target_bucket",
    "continuation_target",
    "move_stage",
    "liquidity_label",
    "exhaustion_risk_level",
)


def build_paper_trading_report(paper_trades: list[dict]) -> dict:
    """Build a performance report from stored paper trade records."""
    trades = [
        trade
        for trade in paper_trades
        if isinstance(trade, dict)
    ]
    open_trades = [
        trade
        for trade in trades
        if str(trade.get("status", "")).lower() == "open"
    ]
    closed_trades = [
        trade
        for trade in trades
        if str(trade.get("status", "")).lower() == "closed"
    ]
    closed_with_pnl = [
        (trade, pnl_pct)
        for trade in closed_trades
        if (pnl_pct := _as_float(trade.get("pnl_pct"))) is not None
    ]
    winning_trades = [
        trade
        for trade, pnl_pct in closed_with_pnl
        if pnl_pct > 0
    ]
    losing_trades = [
        trade
        for trade, pnl_pct in closed_with_pnl
        if pnl_pct < 0
    ]
    breakeven_trades = [
        trade
        for trade, pnl_pct in closed_with_pnl
        if pnl_pct == 0
    ]
    pnl_pct_values = [
        pnl_pct
        for _trade, pnl_pct in closed_with_pnl
    ]
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
        "win_rate_pct": _rate(len(winning_trades), len(closed_trades)),
        "loss_rate_pct": _rate(len(losing_trades), len(closed_trades)),
        "total_pnl_amount": _round(sum(pnl_amount_values)),
        "total_pnl_pct_sum": _round(sum(pnl_pct_values)),
        "average_pnl_pct": _average(pnl_pct_values),
        "average_win_pct": _average(_pnl_values(winning_trades)),
        "average_loss_pct": _average(_pnl_values(losing_trades)),
        "best_trade": _best_trade(closed_trades),
        "worst_trade": _worst_trade(closed_trades),
        "best_symbol": _best_symbol(closed_trades),
        "worst_symbol": _worst_symbol(closed_trades),
        "exit_reason_counts": _count_by_group(closed_trades, "exit_reason"),
    }

    for field in GROUP_FIELDS:
        report[f"average_pnl_by_{field}"] = _average_pnl_by_group(
            closed_trades,
            field,
        )

    return report


def format_paper_trading_report(report: dict) -> str:
    """Format a paper trading report as readable plain text."""
    lines = [
        "Crypto Radar Paper Trading Report",
        "",
        "Overview",
        f"Total trades: {report.get('total_trades', 0)}",
        f"Open trades: {report.get('open_trades', 0)}",
        f"Closed trades: {report.get('closed_trades', 0)}",
        "",
        "Realised P/L",
        f"Total P/L amount: {_format_currency(report.get('total_pnl_amount', 0))}",
        f"Total P/L % sum: {_format_pct(report.get('total_pnl_pct_sum', 0))}%",
        f"Average P/L: {_format_pct(report.get('average_pnl_pct', 0))}%",
        "",
        "Win/Loss Performance",
        f"Wins: {report.get('winning_trades', 0)}",
        f"Losses: {report.get('losing_trades', 0)}",
        f"Breakeven: {report.get('breakeven_trades', 0)}",
        f"Win rate: {_format_pct(report.get('win_rate_pct', 0))}%",
        f"Loss rate: {_format_pct(report.get('loss_rate_pct', 0))}%",
        f"Average win: {_format_pct(report.get('average_win_pct', 0))}%",
        f"Average loss: {_format_pct(report.get('average_loss_pct', 0))}%",
        "",
        "Best/Worst Trades",
        f"Best trade: {_format_trade(report.get('best_trade'))}",
        f"Worst trade: {_format_trade(report.get('worst_trade'))}",
        f"Best symbol: {_format_symbol(report.get('best_symbol'))}",
        f"Worst symbol: {_format_symbol(report.get('worst_symbol'))}",
        "",
        "Exit Reasons",
        *_format_counts(report.get("exit_reason_counts", {})),
        "",
        "Performance by Target Bucket",
        *_format_group_average(report.get("average_pnl_by_target_bucket", {})),
        "",
        "Performance by Continuation Target",
        *_format_group_average(report.get("average_pnl_by_continuation_target", {})),
        "",
        "Performance by Move Stage",
        *_format_group_average(report.get("average_pnl_by_move_stage", {})),
        "",
        "Performance by Liquidity",
        *_format_group_average(report.get("average_pnl_by_liquidity_label", {})),
        "",
        "Performance by Exhaustion Risk",
        *_format_group_average(
            report.get("average_pnl_by_exhaustion_risk_level", {})
        ),
        "",
        "Notes",
        *_build_notes(report),
    ]

    return "\n".join(lines)


def _best_trade(trades: list[dict]) -> dict | None:
    """Return the closed trade with the highest pnl_pct."""
    return _ranked_trade(trades, reverse=True)


def _worst_trade(trades: list[dict]) -> dict | None:
    """Return the closed trade with the lowest pnl_pct."""
    return _ranked_trade(trades, reverse=False)


def _ranked_trade(trades: list[dict], reverse: bool) -> dict | None:
    ranked = [
        _trade_summary(trade, pnl_pct)
        for trade in trades
        if (pnl_pct := _as_float(trade.get("pnl_pct"))) is not None
    ]

    if not ranked:
        return None

    return sorted(ranked, key=lambda trade: trade["pnl_pct"], reverse=reverse)[0]


def _trade_summary(trade: dict, pnl_pct: float) -> dict:
    """Return compact trade details for report rankings."""
    return {
        "id": trade.get("id"),
        "symbol": trade.get("symbol") or "Unknown",
        "pnl_pct": _round(pnl_pct),
        "pnl_amount": _round(_as_float(trade.get("pnl_amount")) or 0.0),
        "exit_reason": trade.get("exit_reason") or "Unknown",
        "target_bucket": trade.get("target_bucket") or "Unknown",
    }


def _best_symbol(trades: list[dict]) -> dict | None:
    """Return the symbol with the strongest average realised pnl_pct."""
    return _ranked_symbol(trades, reverse=True)


def _worst_symbol(trades: list[dict]) -> dict | None:
    """Return the symbol with the weakest average realised pnl_pct."""
    return _ranked_symbol(trades, reverse=False)


def _ranked_symbol(trades: list[dict], reverse: bool) -> dict | None:
    grouped: dict[str, list[float]] = {}

    for trade in trades:
        pnl_pct = _as_float(trade.get("pnl_pct"))

        if pnl_pct is None:
            continue

        symbol = str(trade.get("symbol") or "Unknown")
        grouped.setdefault(symbol, []).append(pnl_pct)

    if not grouped:
        return None

    ranked = [
        {
            "symbol": symbol,
            "count": len(values),
            "average_pnl_pct": _average(values),
            "total_pnl_pct": _round(sum(values)),
        }
        for symbol, values in grouped.items()
    ]

    return sorted(
        ranked,
        key=lambda symbol: symbol["average_pnl_pct"],
        reverse=reverse,
    )[0]


def _average_pnl_by_group(trades: list[dict], group_key: str) -> dict:
    """Average realised pnl_pct by one trade attribute."""
    grouped: dict[str, list[float]] = {}

    for trade in trades:
        pnl_pct = _as_float(trade.get("pnl_pct"))

        if pnl_pct is None:
            continue

        group = str(trade.get(group_key) or "Unknown")
        grouped.setdefault(group, []).append(pnl_pct)

    return {
        group: _average(values)
        for group, values in sorted(grouped.items())
    }


def _count_by_group(trades: list[dict], group_key: str) -> dict:
    """Count trades by one trade attribute."""
    counts: dict[str, int] = {}

    for trade in trades:
        group = str(trade.get(group_key) or "Unknown")
        counts[group] = counts.get(group, 0) + 1

    return dict(sorted(counts.items()))


def _pnl_values(trades: list[dict]) -> list[float]:
    """Return numeric pnl_pct values from trades."""
    return [
        pnl_pct
        for trade in trades
        if (pnl_pct := _as_float(trade.get("pnl_pct"))) is not None
    ]


def _average(values: list[float]) -> float:
    """Return an average rounded to two decimals."""
    if not values:
        return 0.0

    return _round(sum(values) / len(values))


def _rate(count: int, total: int) -> float:
    """Return a percentage rate rounded to two decimals."""
    if total == 0:
        return 0.0

    return _round((count / total) * 100)


def _as_float(value) -> float | None:
    """Convert a value to float when possible."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: float) -> float:
    """Round numeric report values consistently."""
    return round(value, 2)


def _format_trade(trade: dict | None) -> str:
    """Format one ranked trade."""
    if not trade:
        return "Not available"

    return (
        f"{trade.get('symbol', 'Unknown')} "
        f"({_format_pct(trade.get('pnl_pct', 0))}%, "
        f"{_format_currency(trade.get('pnl_amount', 0))}, "
        f"{trade.get('exit_reason', 'Unknown')})"
    )


def _format_symbol(symbol: dict | None) -> str:
    """Format one ranked symbol."""
    if not symbol:
        return "Not available"

    return (
        f"{symbol.get('symbol', 'Unknown')} "
        f"({_format_pct(symbol.get('average_pnl_pct', 0))}% avg, "
        f"{symbol.get('count', 0)} trades)"
    )


def _format_counts(counts: dict) -> list[str]:
    """Format count mappings."""
    if not counts:
        return ["- Not available"]

    return [
        f"- {group}: {count}"
        for group, count in counts.items()
    ]


def _format_group_average(group_averages: dict) -> list[str]:
    """Format grouped average pnl values."""
    if not group_averages:
        return ["- Not available"]

    return [
        f"- {group}: {_format_pct(average)}%"
        for group, average in group_averages.items()
    ]


def _build_notes(report: dict) -> list[str]:
    """Build plain-English notes for the report."""
    notes = []

    if report.get("total_trades", 0) == 0:
        notes.append(
            "No paper trades available yet. Let the radar create simulated trades first."
        )

    if report.get("closed_trades", 0) == 0:
        notes.append(
            "No closed paper trades yet. Let open trades hit take-profit, stop-loss, or max hold expiry."
        )

    if report.get("closed_trades", 0) < 10:
        notes.append("Sample size is still small. Avoid drawing strong conclusions yet.")

    if report.get("win_rate_pct", 0) < 40 and report.get("closed_trades", 0) >= 10:
        notes.append(
            "Win rate is weak. Review entry criteria before considering live trading."
        )

    if report.get("average_loss_pct", 0) < -5:
        notes.append("Average loss is high. Review stop-loss and entry quality.")

    if not notes:
        notes.append("Paper trading sample is large enough for early review.")

    return [f"- {note}" for note in notes]


def _format_pct(value) -> str:
    """Format a numeric percentage without noisy trailing zeros."""
    number = _as_float(value) or 0.0
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _format_currency(value) -> str:
    """Format a numeric P/L amount."""
    number = _as_float(value) or 0.0
    sign = "-" if number < 0 else ""
    return f"{sign}${abs(number):.2f}"
