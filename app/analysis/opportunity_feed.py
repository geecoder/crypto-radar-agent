"""Ranked opportunity feed — the primary output of the discretionary
decision-support pivot.

Five backtested strategy families (see app/analysis/backtest.py,
exit_model_backtest.py, mean_reversion_backtest.py, liquid_majors_backtest.py)
found no autonomous edge after real costs. But the scanner reliably finds
real movers, and that has genuine value to a human decision-maker who brings
their own judgment. This module ranks CURRENT live alert candidates by a
composite of opportunity_score, tradability_score, REAL current order-book
liquidity (not just the coarse label), and the historical follow-through
rate of that alert's alert_type (app.analysis.base_rates) — then shows the
human every input behind that ranking. It never outputs a decision, only
the inputs to make one.
"""

from typing import Any, Callable

from app.analysis.base_rates import DEFAULT_HIT_THRESHOLD_PCT, format_base_rate_line
from app.exchange.binance_executor import evaluate_entry_slippage
from app.trading.paper_trading import (
    _get_liquidity_label,
    _get_opportunity_value,
    _get_tradability_score,
)

# Ranking weights -- opportunity_score is weighted highest since it's the
# broadest "is this a good setup" signal; the other three each check a
# different way that signal could be misleading (execution quality right
# now, execution quality historically, and whether this alert TYPE has
# ever actually followed through).
COMPOSITE_WEIGHTS = {
    "opportunity_score": 0.35,
    "tradability_score": 0.15,
    "liquidity_headroom": 0.25,
    "base_rate": 0.25,
}
# A representative position size for the live liquidity check -- this feed
# ranks setups for a human to size themselves, so this is just a fixed
# reference point for "how deep is the book right now," not a real order.
REFERENCE_POSITION_SIZE_USD = 200.0
SLIPPAGE_BUDGET_PCT = 1.5  # matches PAPER_SLIPPAGE_BUDGET_PCT's default

LiveLiquidityCheck = Callable[[str, float, float], dict]


def _safe_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def check_live_liquidity(
    symbol: str,
    entry_price: float,
    position_size_usd: float = REFERENCE_POSITION_SIZE_USD,
) -> dict:
    """Fetch the CURRENT order book and return real spread/slippage for a
    representative position size — the actual book right now, not the
    coarse 24h-volume-based tradability_score.
    """
    if entry_price is None or entry_price <= 0:
        return {"spread_pct": None, "adverse_slippage_pct": None, "headroom_score": 0.0}

    quantity = position_size_usd / entry_price
    result = evaluate_entry_slippage(symbol, quantity, entry_price, SLIPPAGE_BUDGET_PCT)
    adverse_slippage_pct = result.get("adverse_slippage_pct")

    if adverse_slippage_pct is None:
        return {
            "spread_pct": result.get("spread_pct"),
            "adverse_slippage_pct": None,
            "headroom_score": 0.0,
        }

    headroom_score = max(
        0.0,
        min(100.0, (SLIPPAGE_BUDGET_PCT - adverse_slippage_pct) / SLIPPAGE_BUDGET_PCT * 100),
    )

    return {
        "spread_pct": result.get("spread_pct"),
        "adverse_slippage_pct": adverse_slippage_pct,
        "headroom_score": headroom_score,
    }


def compute_composite_score(
    result: dict,
    base_rate_stats_by_type: dict,
    hit_threshold_pct: int = DEFAULT_HIT_THRESHOLD_PCT,
    live_liquidity_check: LiveLiquidityCheck = check_live_liquidity,
) -> dict:
    """Score one live alert candidate for ranking.

    Returns the composite score PLUS every raw input that fed it, so the
    caller displays decision inputs to a human rather than just a number.
    """
    symbol = str(result.get("symbol") or "UNKNOWN")
    alert_type = str(result.get("alert_type") or "Unknown")
    opportunity_score = _safe_float(_get_opportunity_value(result, "opportunity_score")) or 0.0
    tradability_score = _safe_float(_get_tradability_score(result)) or 0.0
    liquidity_label = _get_liquidity_label(result)
    entry_price = _safe_float(result.get("latest_close"), default=None)

    if entry_price is not None and entry_price > 0:
        liquidity = live_liquidity_check(symbol, entry_price, REFERENCE_POSITION_SIZE_USD)
    else:
        liquidity = {"spread_pct": None, "adverse_slippage_pct": None, "headroom_score": 0.0}

    base_rate_stats = base_rate_stats_by_type.get(alert_type) or {}
    base_rate_pct = base_rate_stats.get("hit_rate_pct", 0.0)

    composite_score = (
        opportunity_score * COMPOSITE_WEIGHTS["opportunity_score"]
        + tradability_score * COMPOSITE_WEIGHTS["tradability_score"]
        + liquidity["headroom_score"] * COMPOSITE_WEIGHTS["liquidity_headroom"]
        + base_rate_pct * COMPOSITE_WEIGHTS["base_rate"]
    )

    return {
        "symbol": symbol,
        "alert_type": alert_type,
        "composite_score": round(composite_score, 1),
        "opportunity_score": opportunity_score,
        "tradability_score": tradability_score,
        "liquidity_label": liquidity_label,
        "spread_pct": liquidity["spread_pct"],
        "adverse_slippage_pct": liquidity["adverse_slippage_pct"],
        "base_rate_stats": base_rate_stats,
        "hit_threshold_pct": hit_threshold_pct,
        "entry_price": entry_price,
    }


def rank_opportunities(
    candidates: list[dict],
    base_rate_stats_by_type: dict,
    hit_threshold_pct: int = DEFAULT_HIT_THRESHOLD_PCT,
    live_liquidity_check: LiveLiquidityCheck = check_live_liquidity,
    top_n: int = 10,
) -> list[dict]:
    """Score and rank every live candidate, best composite score first."""
    scored = [
        compute_composite_score(
            candidate, base_rate_stats_by_type, hit_threshold_pct, live_liquidity_check
        )
        for candidate in candidates
    ]

    return sorted(scored, key=lambda item: -item["composite_score"])[:top_n]


def format_opportunity_feed(ranked: list[dict]) -> str:
    """Format a rank_opportunities() result as a Telegram HTML message.

    Shows decision inputs per setup — never a buy/sell recommendation.
    """
    if not ranked:
        return (
            "📡 <b>Ranked Opportunity Feed</b>\n\n"
            "No live setups right now. This is a monitoring signal only — "
            "not a recommendation to trade."
        )

    lines = [
        "📡 <b>Ranked Opportunity Feed</b>",
        "Decision inputs, not a decision — not financial advice.",
        "",
    ]

    for rank, item in enumerate(ranked, start=1):
        base_rate_line = format_base_rate_line(
            item["alert_type"],
            {item["alert_type"]: item["base_rate_stats"]} if item["base_rate_stats"] else {},
            item["hit_threshold_pct"],
        )
        spread_str = f"{item['spread_pct']:.3f}%" if item["spread_pct"] is not None else "unknown"

        lines.append(
            f"{rank}. <b>{item['symbol']}</b> — {item['alert_type']}\n"
            f"   Opportunity {item['opportunity_score']:.0f} · "
            f"Tradability {item['tradability_score']:.0f} · "
            f"{item['liquidity_label'] or 'Unknown'} liquidity · "
            f"current spread {spread_str}\n"
            f"   {base_rate_line}\n"
            f"   Rank score: {item['composite_score']:.1f}/100"
        )

    return "\n\n".join(lines)
