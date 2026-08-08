"""Honest replay of the Block 1-4 reconciled trading logic over historical alerts.

Reuses the exact production eligibility (`should_create_paper_trade`,
`should_create_parabolic_paper_trade`, `classify_explosive_mover`) and exit
simulation (`evaluate_open_paper_trade`) functions against stored
`alert_history` rows and real historical Binance klines — no separate
backtest engine reimplements that logic.

No historical order-book data exists (real slippage measurement only started
with Block 2), so position sizing and the slippage gate fall back to the flat
`SLIPPAGE_PCT_BY_LIQUIDITY` estimate instead of a real depth walk. This is
disclosed in every report this module produces (`BACKTEST_APPROXIMATION_NOTE`)
because it likely overstates how many thin-liquidity coins would truly clear
a real slippage-budget check.
"""

from typing import Any, Callable

from app.indicators.explosive_mover import classify_explosive_mover
from app.trading.paper_trading import (
    DEFAULT_SLIPPAGE_PCT,
    PARABOLIC_WATCH_ALERT_TYPE,
    PAPER_TRADE_ALLOWED_ALERT_TYPES,
    POSITION_SIZE_MAX_MULTIPLIER,
    POSITION_SIZE_MIN_MULTIPLIER,
    POSITION_SIZE_OPPORTUNITY_WEIGHT,
    POSITION_SIZE_TRADABILITY_WEIGHT,
    SLIPPAGE_PCT_BY_LIQUIDITY,
    _score_based_max_hold_hours,
    evaluate_open_paper_trade,
    should_create_paper_trade,
    should_create_parabolic_paper_trade,
)
from app.trading.strategy_config import (
    get_default_paper_trading_strategy,
    get_parabolic_paper_strategy,
)
from app.risk.risk_manager import compute_position_size

BACKTEST_LOOKBACK_DAYS = 60
# Alerts newer than this can't have a resolved outcome yet (need the full
# forward window to know if/how the trade would have exited).
BACKTEST_MIN_AGE_HOURS = 48
# Default budget mirrored here rather than imported from app.config, so this
# module never needs live config wiring to run against historical data.
BACKTEST_SLIPPAGE_BUDGET_PCT = 1.5
BACKTEST_APPROXIMATION_NOTE = (
    "No historical order-book data exists before Block 2 shipped — slippage "
    "and position sizing here use the flat liquidity-tiered estimate, not a "
    "real depth walk. This likely OVERSTATES how many thin-liquidity coins "
    "would truly clear a real slippage-budget check; treat trade counts as "
    "an upper bound, not a guarantee."
)

# Approximate liquidity_score from the stored label — alert_history only
# keeps the label, not the 24h volume/trade-count that produced it, so this
# mirrors app/indicators/liquidity.py's score bands rather than recomputing.
_LIQUIDITY_LABEL_TO_SCORE = {
    "excellent": 100,
    "strong": 80,
    "good": 60,
    "thin": 40,
    "very thin": 10,
}

KlinesFetcher = Callable[[str, int, int], list]


def _safe_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def reconstruct_scan_result(alert_row: dict, new_alert_type: str) -> dict:
    """Build a scan-result-shaped dict from a stored alert_history row.

    Flattened top-level keys with nested fallbacks match what
    app/trading/paper_trading.py's `_get_*` accessors expect, so the real
    eligibility functions run unmodified against historical data.
    """
    return {
        "symbol": alert_row.get("symbol"),
        "latest_close": alert_row.get("latest_close"),
        "alert_type": new_alert_type,
        "opportunity_score": alert_row.get("opportunity_score"),
        "move_from_recent_low_pct": alert_row.get("move_from_recent_low_pct"),
        "liquidity_label": alert_row.get("liquidity_label"),
        "exhaustion_risk_level": alert_row.get("exhaustion_risk_level"),
        "recent_price_changes": alert_row.get("recent_price_changes") or {},
        "volume_acceleration": alert_row.get("volume_acceleration") or {},
    }


def classify_under_new_rules(alert_row: dict) -> str:
    """Return the alert type this historical row gets under the Block 3
    reconciled `classify_explosive_mover`, with the same score-based
    Continuation Alert fallback the live scanner uses."""
    liquidity_label = str(alert_row.get("liquidity_label") or "").strip().lower()
    liquidity_score = _LIQUIDITY_LABEL_TO_SCORE.get(liquidity_label, 0)

    classification = classify_explosive_mover(
        {"move_from_recent_low_pct": alert_row.get("move_from_recent_low_pct")},
        alert_row.get("recent_price_changes") or {},
        alert_row.get("volume_acceleration") or {},
        {"label": alert_row.get("liquidity_label"), "score": liquidity_score},
        {"risk_level": alert_row.get("exhaustion_risk_level") or "Low"},
        alert_row.get("breakout_signal") or {},
        alert_row.get("trend_signal") or {},
        alert_row.get("volatility_signal") or {},
    )

    if classification.get("should_alert"):
        return classification.get("alert_type")

    if (_safe_float(alert_row.get("opportunity_score"), default=0) or 0) >= 60:
        return "Continuation Alert"

    return "No Alert"


def evaluate_new_eligibility(
    alert_row: dict, new_alert_type: str
) -> tuple[bool, str, Any]:
    """Return (eligible, reason, strategy) under the Block 3 reconciled rules."""
    result = reconstruct_scan_result(alert_row, new_alert_type)

    if new_alert_type == PARABOLIC_WATCH_ALERT_TYPE:
        strategy = get_parabolic_paper_strategy()
        eligible, reason = should_create_parabolic_paper_trade(result, strategy)
        return eligible, reason, strategy

    if new_alert_type not in PAPER_TRADE_ALLOWED_ALERT_TYPES:
        return False, f"{new_alert_type} is not eligible for paper trading.", None

    strategy = get_default_paper_trading_strategy()
    eligible, reason = should_create_paper_trade(result, strategy)
    return eligible, reason, strategy


def estimate_conviction_position_size(alert_row: dict, strategy: Any) -> tuple[float, float]:
    """Flat-estimate version of compute_conviction_position_size for
    backtesting — no historical order-book data exists to measure real
    slippage or depth, so this uses the same flat liquidity-tiered estimate
    `evaluate_open_paper_trade`'s net P&L falls back to.

    Returns (position_size_usd, estimated_slippage_pct).
    """
    liquidity_label = str(alert_row.get("liquidity_label") or "").strip().lower()
    estimated_slippage_pct = SLIPPAGE_PCT_BY_LIQUIDITY.get(
        liquidity_label, DEFAULT_SLIPPAGE_PCT
    )

    base_size = compute_position_size(float(strategy.stop_loss_pct or -10))
    tradability_headroom = max(
        0.0,
        min(
            1.0,
            (BACKTEST_SLIPPAGE_BUDGET_PCT - estimated_slippage_pct)
            / BACKTEST_SLIPPAGE_BUDGET_PCT,
        ),
    )
    normalized_score = max(
        0.0,
        min(1.0, (_safe_float(alert_row.get("opportunity_score"), default=0) or 0) / 100),
    )
    conviction = (
        normalized_score * POSITION_SIZE_OPPORTUNITY_WEIGHT
        + tradability_headroom * POSITION_SIZE_TRADABILITY_WEIGHT
    )
    multiplier = POSITION_SIZE_MIN_MULTIPLIER + conviction * (
        POSITION_SIZE_MAX_MULTIPLIER - POSITION_SIZE_MIN_MULTIPLIER
    )

    return round(base_size * multiplier, 2), estimated_slippage_pct


def simulate_new_trade_exit(
    alert_row: dict,
    strategy: Any,
    position_size_usd: float,
    klines: list,
) -> dict | None:
    """Simulate the trade's lifecycle using the real evaluate_open_paper_trade().

    Returns close-update fields, or None if the trade never resolves within
    the fetched candle window (treated as an unresolved/excluded outcome,
    not a loss or a win).
    """
    from app.binance.client import klines_to_dataframe

    entry_price = _safe_float(alert_row.get("latest_close"), default=None)
    alerted_at = alert_row.get("alerted_at")

    if entry_price is None or entry_price <= 0 or not klines:
        return None

    candles = klines_to_dataframe(klines)

    if candles.empty:
        return None

    opened_at = alerted_at.isoformat() if hasattr(alerted_at, "isoformat") else alerted_at
    max_hold_hours = _score_based_max_hold_hours(
        alert_row.get("opportunity_score"), strategy
    )

    trade = {
        "entry_price": entry_price,
        "opened_at": opened_at,
        "stop_loss_pct": strategy.stop_loss_pct,
        "take_profit_1_pct": strategy.take_profit_1_pct,
        "take_profit_2_pct": strategy.take_profit_2_pct,
        "take_profit_3_pct": strategy.take_profit_3_pct,
        "max_hold_hours": max_hold_hours,
        "liquidity_label": alert_row.get("liquidity_label"),
        "simulated_position_size": position_size_usd,
    }

    updates = evaluate_open_paper_trade(trade, candles)

    if updates.get("status") != "closed":
        return None

    return updates


def backtest_alert(alert_row: dict, klines_fetcher: KlinesFetcher) -> dict:
    """Backtest one historical alert under the new reconciled rules.

    `klines_fetcher(symbol, start_time_ms, max_hold_hours) -> list[list]` is
    injected so callers control how historical candles are sourced (real
    Binance client in production use, a stub in tests).
    """
    new_alert_type = classify_under_new_rules(alert_row)
    eligible, reason, strategy = evaluate_new_eligibility(alert_row, new_alert_type)

    outcome = {
        "symbol": alert_row.get("symbol"),
        "alerted_at": alert_row.get("alerted_at"),
        "old_alert_type": alert_row.get("alert_type"),
        "new_alert_type": new_alert_type,
        "actual_paper_trade_created": bool(alert_row.get("paper_trade_created")),
        "would_trade": False,
        "reason": reason,
        "strategy_name": strategy.name if strategy else None,
        "position_size_usd": None,
        "exit_reason": None,
        "gross_pnl_pct": None,
        "net_pnl_pct": None,
    }

    if not eligible:
        return outcome

    position_size_usd, _estimated_slippage_pct = estimate_conviction_position_size(
        alert_row, strategy
    )
    outcome["position_size_usd"] = position_size_usd

    alerted_at = alert_row.get("alerted_at")
    start_time_ms = int(alerted_at.timestamp() * 1000)
    # Fetch the score-adjusted hold window (high-scoring trades can extend to
    # strategy.high_score_max_hold_hours) so the candle window always covers
    # whatever evaluate_open_paper_trade will actually look for.
    max_hold_hours = _score_based_max_hold_hours(
        alert_row.get("opportunity_score"), strategy
    )
    klines = klines_fetcher(alert_row.get("symbol"), start_time_ms, max_hold_hours)

    close_updates = simulate_new_trade_exit(alert_row, strategy, position_size_usd, klines)

    if close_updates is None:
        outcome["reason"] = "Eligible but no resolved outcome (insufficient candle data)."
        return outcome

    outcome.update(
        {
            "would_trade": True,
            "exit_reason": close_updates.get("exit_reason"),
            "gross_pnl_pct": close_updates.get("gross_pnl_pct"),
            "net_pnl_pct": close_updates.get("net_pnl_pct"),
        }
    )
    return outcome


def _bucket_stats(rows: list[dict]) -> dict:
    """Return count/win-rate/avg-net-pnl for a set of traded backtest rows."""
    count = len(rows)

    if count == 0:
        return {"count": 0, "win_rate": 0.0, "avg_net_pnl_pct": 0.0}

    wins = sum(1 for r in rows if (r.get("net_pnl_pct") or 0) > 0)
    avg_net_pnl_pct = sum(r.get("net_pnl_pct") or 0 for r in rows) / count

    return {
        "count": count,
        "win_rate": round(wins / count * 100, 1),
        "avg_net_pnl_pct": round(avg_net_pnl_pct, 2),
    }


def run_backtest(alert_rows: list[dict], klines_fetcher: KlinesFetcher) -> dict:
    """Backtest every alert row and aggregate results.

    Returns total/eligible counts, overall and per-strategy win rate and
    expectancy, and the raw per-alert results for further inspection (e.g.
    checking specific symbols like HEIUSDT/CTSIUSDT).
    """
    results = [backtest_alert(row, klines_fetcher) for row in alert_rows]
    traded = [r for r in results if r["would_trade"]]
    actual_traded_count = sum(1 for r in results if r["actual_paper_trade_created"])

    by_strategy: dict[str, list[dict]] = {}
    for row in traded:
        by_strategy.setdefault(row["strategy_name"] or "unknown", []).append(row)

    return {
        "approximation_note": BACKTEST_APPROXIMATION_NOTE,
        "total_alerts_replayed": len(results),
        "new_logic_would_trade_count": len(traded),
        "actual_historical_trade_count": actual_traded_count,
        "overall": _bucket_stats(traded),
        "by_strategy": {
            name: _bucket_stats(rows) for name, rows in by_strategy.items()
        },
        "results": results,
    }


def format_backtest_report(report: dict) -> str:
    """Format a run_backtest() report as human-readable text."""
    lines = [
        "60-Day Backtest — Reconciled Blocks 1-4 Logic",
        "=" * 48,
        f"NOTE: {report['approximation_note']}",
        "",
        f"Alerts replayed: {report['total_alerts_replayed']}",
        f"Would trade under new logic: {report['new_logic_would_trade_count']}",
        f"Actually traded historically: {report['actual_historical_trade_count']}",
        "",
        "Overall (new logic):",
        (
            f"  {report['overall']['count']} trades, "
            f"{report['overall']['win_rate']:.1f}% win rate, "
            f"{report['overall']['avg_net_pnl_pct']:+.2f}% avg net P&L"
        ),
        "",
        "By strategy:",
    ]

    for name, stats in report["by_strategy"].items():
        lines.append(
            f"  {name}: {stats['count']} trades, {stats['win_rate']:.1f}% win rate, "
            f"{stats['avg_net_pnl_pct']:+.2f}% avg net P&L"
        )

    return "\n".join(lines)
