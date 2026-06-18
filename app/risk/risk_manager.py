"""Portfolio-level risk controls for the crypto radar paper trading engine.

All checks run BEFORE a paper trade is created. Every rule can be tuned via
environment variables so live-trading thresholds can be tightened without code
changes. Wire this into the paper-trading path only — never live orders until
LIVE_TRADING_ENABLED=true AND all go-live preconditions pass.
"""

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Configuration (all tunable via env vars, all safe defaults)
# ---------------------------------------------------------------------------

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class RiskConfig:
    """Configurable risk limits. Override via env vars at deploy time."""

    # Gate 1: max simultaneous open positions across the whole portfolio.
    max_open_positions: int = field(
        default_factory=lambda: _env_int("RISK_MAX_OPEN_POSITIONS", 5)
    )
    # Gate 2: max fraction of portfolio deployed at once (0.0–1.0).
    max_capital_deployed_pct: float = field(
        default_factory=lambda: _env_float("RISK_MAX_CAPITAL_PCT", 30.0)
    )
    # Gate 3: portfolio value used for position sizing ($).
    portfolio_value: float = field(
        default_factory=lambda: _env_float("RISK_PORTFOLIO_VALUE", 1000.0)
    )
    # Gate 3: risk exactly this fraction of portfolio per trade.
    risk_per_trade_pct: float = field(
        default_factory=lambda: _env_float("RISK_PER_TRADE_PCT", 1.0)
    )
    # Gate 4: daily drawdown circuit-breaker threshold (%).
    daily_drawdown_halt_pct: float = field(
        default_factory=lambda: _env_float("RISK_DAILY_DRAWDOWN_HALT_PCT", 5.0)
    )
    # Gate 5: max positions in highly-correlated coin groups.
    max_correlated_positions: int = field(
        default_factory=lambda: _env_int("RISK_MAX_CORRELATED_POSITIONS", 2)
    )


@dataclass
class RiskDecision:
    """Result of a risk check. allowed=False means the trade must NOT open."""

    allowed: bool
    reason: str
    position_size_usd: float | None = None


# ---------------------------------------------------------------------------
# Correlation groups (coins that move together count as one bet)
# ---------------------------------------------------------------------------

# Each set is one correlated group. A coin's base asset is compared against
# every group. Extend this list as market structure evolves.
CORRELATED_GROUPS: list[frozenset[str]] = [
    frozenset({"DOGE", "SHIB", "PEPE", "FLOKI", "BONK", "WIF", "MEME", "BRETT"}),
    frozenset({"BTC", "ETH"}),  # majors move together
    frozenset({"SOL", "AVAX", "SUI", "APT"}),  # L1 alts
    frozenset({"BNB", "OKB", "HT"}),  # exchange tokens
]


def _base_asset(symbol: str) -> str:
    """Extract the base asset from a USDT or BUSD trading pair."""
    for quote in ("USDT", "BUSD", "BTC", "ETH", "BNB"):
        if symbol.upper().endswith(quote):
            return symbol.upper()[: -len(quote)]
    return symbol.upper()


def _correlated_group(base: str) -> frozenset[str] | None:
    """Return the correlation group that contains this base asset, or None."""
    for group in CORRELATED_GROUPS:
        if base in group:
            return group
    return None


# ---------------------------------------------------------------------------
# Core risk checks
# ---------------------------------------------------------------------------

def check_position_limit(
    open_trades: list[dict],
    config: RiskConfig | None = None,
) -> RiskDecision:
    """Gate 1 — refuse if already at the max concurrent position count."""
    cfg = config or RiskConfig()
    open_count = sum(1 for t in open_trades if t.get("status") == "open")

    if open_count >= cfg.max_open_positions:
        return RiskDecision(
            allowed=False,
            reason=(
                f"Position limit reached: {open_count}/{cfg.max_open_positions} "
                "open positions."
            ),
        )
    return RiskDecision(allowed=True, reason="Position limit OK.")


def check_capital_exposure(
    open_trades: list[dict],
    config: RiskConfig | None = None,
) -> RiskDecision:
    """Gate 2 — refuse if total simulated capital deployed exceeds the cap."""
    cfg = config or RiskConfig()
    deployed = sum(
        float(t.get("simulated_position_size") or 0)
        for t in open_trades
        if t.get("status") == "open"
    )
    cap = cfg.portfolio_value * (cfg.max_capital_deployed_pct / 100)

    if deployed >= cap:
        return RiskDecision(
            allowed=False,
            reason=(
                f"Capital cap reached: ${deployed:.0f} deployed ≥ "
                f"${cap:.0f} ({cfg.max_capital_deployed_pct:.0f}% of "
                f"${cfg.portfolio_value:.0f} portfolio)."
            ),
        )
    return RiskDecision(allowed=True, reason="Capital exposure OK.")


def compute_position_size(
    stop_loss_pct: float,
    config: RiskConfig | None = None,
) -> float:
    """Gate 3 — compute position size so we risk exactly risk_per_trade_pct.

    Formula: position_size = (portfolio × risk%) / |stop_loss_pct|
    """
    cfg = config or RiskConfig()

    if stop_loss_pct >= 0:
        return cfg.portfolio_value * (cfg.risk_per_trade_pct / 100)

    dollar_risk = cfg.portfolio_value * (cfg.risk_per_trade_pct / 100)
    position_size = dollar_risk / (abs(stop_loss_pct) / 100)
    return round(position_size, 2)


def check_daily_drawdown(
    closed_trades_today: list[dict],
    config: RiskConfig | None = None,
) -> RiskDecision:
    """Gate 4 — halt if portfolio dropped more than daily_drawdown_halt_pct in 24h.

    Computes realised P&L from trades closed in the last 24 hours.
    """
    cfg = config or RiskConfig()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    recent_pnl = 0.0
    for trade in closed_trades_today:
        closed_at_raw = trade.get("closed_at")
        if not closed_at_raw:
            continue
        try:
            closed_at = datetime.fromisoformat(str(closed_at_raw))
            if closed_at.tzinfo is None:
                closed_at = closed_at.replace(tzinfo=timezone.utc)
            if closed_at < cutoff:
                continue
        except (ValueError, TypeError):
            continue

        recent_pnl += float(trade.get("pnl_amount") or 0)

    drawdown_pct = (abs(recent_pnl) / cfg.portfolio_value * 100) if recent_pnl < 0 else 0

    if drawdown_pct >= cfg.daily_drawdown_halt_pct:
        return RiskDecision(
            allowed=False,
            reason=(
                f"Daily drawdown circuit breaker: portfolio down "
                f"{drawdown_pct:.1f}% (${abs(recent_pnl):.2f}) in 24h — "
                f"threshold is {cfg.daily_drawdown_halt_pct:.1f}%. "
                "No new entries until the circuit resets."
            ),
        )
    return RiskDecision(
        allowed=True,
        reason=f"Daily drawdown OK ({drawdown_pct:.1f}% in 24h).",
    )


def check_correlation(
    symbol: str,
    open_trades: list[dict],
    config: RiskConfig | None = None,
) -> RiskDecision:
    """Gate 5 — refuse if too many correlated positions are already open."""
    cfg = config or RiskConfig()
    base = _base_asset(symbol)
    group = _correlated_group(base)

    if group is None:
        return RiskDecision(allowed=True, reason="No correlation group found.")

    count = sum(
        1
        for t in open_trades
        if t.get("status") == "open" and _base_asset(t.get("symbol", "")) in group
    )

    if count >= cfg.max_correlated_positions:
        return RiskDecision(
            allowed=False,
            reason=(
                f"Correlation limit: already {count} open position(s) in the "
                f"same group as {base} — max is {cfg.max_correlated_positions}."
            ),
        )
    return RiskDecision(allowed=True, reason="Correlation check OK.")


# ---------------------------------------------------------------------------
# Composite gate — run all checks in sequence
# ---------------------------------------------------------------------------

def evaluate_trade_risk(
    symbol: str,
    stop_loss_pct: float,
    open_trades: list[dict],
    closed_trades_today: list[dict],
    config: RiskConfig | None = None,
) -> RiskDecision:
    """Run all five risk gates and return the first failure (or allow).

    Call this before opening any paper (or live) trade. If the result is
    allowed=False, skip the trade and log the reason.
    """
    cfg = config or RiskConfig()

    for check, kwargs in [
        (check_position_limit, {"open_trades": open_trades, "config": cfg}),
        (check_capital_exposure, {"open_trades": open_trades, "config": cfg}),
        (check_daily_drawdown, {"closed_trades_today": closed_trades_today, "config": cfg}),
        (check_correlation, {"symbol": symbol, "open_trades": open_trades, "config": cfg}),
    ]:
        decision = check(**kwargs)
        if not decision.allowed:
            return decision

    position_size = compute_position_size(stop_loss_pct, cfg)
    return RiskDecision(
        allowed=True,
        reason="All risk gates passed.",
        position_size_usd=position_size,
    )
