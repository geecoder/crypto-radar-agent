"""Binance spot order executor with shadow-mode and hard go-live gates.

LIVE_TRADING_ENABLED defaults to FALSE. When false this module logs what it
WOULD do but never calls the exchange. Shadow mode runs the executor in
parallel with paper trades and logs would-be orders to `shadow_trades` for
side-by-side comparison without risking money.

Go-live requires ALL preconditions to pass — checked at startup. If any fail,
the bot prints which gate failed and refuses to trade live.
"""

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------

LIVE_TRADING_ENABLED: bool = (
    os.getenv("LIVE_TRADING_ENABLED", "false").strip().lower() == "true"
)
SHADOW_MODE_ENABLED: bool = (
    os.getenv("SHADOW_MODE_ENABLED", "true").strip().lower() == "true"
)

# Live-trading position limits (separate from paper trading).
LIVE_MAX_POSITIONS: int = 3
LIVE_MAX_CAPITAL_PCT: float = 5.0  # 5% of portfolio in live trades at once


# ---------------------------------------------------------------------------
# Go-live precondition gates
# ---------------------------------------------------------------------------

@dataclass
class GoLiveGate:
    name: str
    passed: bool
    detail: str


def check_go_live_preconditions(
    closed_paper_trade_count: int,
    win_rate_last_100: float,
    avg_pnl_last_100: float,
    telegram_send_rate_7d: float,
    risk_manager_active: bool,
) -> list[GoLiveGate]:
    """Evaluate all go-live gates. ALL must pass before live trading is enabled.

    Gates:
    1. >= 100 closed paper trades
    2. >= 55% win rate over last 100 trades
    3. Positive average P&L over last 100 trades
    4. Telegram send rate >= 90% over last 7 days
    5. risk_manager module active and tested
    """
    return [
        GoLiveGate(
            name="min_paper_trades",
            passed=closed_paper_trade_count >= 100,
            detail=(
                f"{closed_paper_trade_count}/100 closed paper trades "
                f"({'PASS' if closed_paper_trade_count >= 100 else 'FAIL — need 100+'})."
            ),
        ),
        GoLiveGate(
            name="min_win_rate",
            passed=win_rate_last_100 >= 55.0,
            detail=(
                f"Win rate over last 100 trades: {win_rate_last_100:.1f}% "
                f"({'PASS' if win_rate_last_100 >= 55.0 else 'FAIL — need >= 55%'})."
            ),
        ),
        GoLiveGate(
            name="positive_avg_pnl",
            passed=avg_pnl_last_100 > 0,
            detail=(
                f"Avg P&L over last 100 trades: {avg_pnl_last_100:+.2f}% "
                f"({'PASS' if avg_pnl_last_100 > 0 else 'FAIL — must be positive'})."
            ),
        ),
        GoLiveGate(
            name="telegram_send_rate",
            passed=telegram_send_rate_7d >= 90.0,
            detail=(
                f"Telegram send rate (7d): {telegram_send_rate_7d:.1f}% "
                f"({'PASS' if telegram_send_rate_7d >= 90.0 else 'FAIL — need >= 90%'})."
            ),
        ),
        GoLiveGate(
            name="risk_manager_active",
            passed=risk_manager_active,
            detail=(
                "risk_manager module: "
                f"{'PASS — active' if risk_manager_active else 'FAIL — not initialised'}."
            ),
        ),
    ]


def all_go_live_gates_pass(gates: list[GoLiveGate]) -> bool:
    return all(g.passed for g in gates)


def format_go_live_report(gates: list[GoLiveGate]) -> str:
    """Format a human-readable console go-live readiness table."""
    lines = ["Go-Live Readiness Check", "=" * 40]
    for gate in gates:
        status = "✅ PASS" if gate.passed else "❌ FAIL"
        lines.append(f"{status}  {gate.detail}")
    overall = "READY" if all_go_live_gates_pass(gates) else "NOT READY"
    lines.append("=" * 40)
    lines.append(f"Overall: {overall}")
    return "\n".join(lines)


def _verdict(
    gates: list[GoLiveGate],
    win_rate_this_week: float,
    win_rate_last_week: float,
) -> str:
    """Return a one-line human verdict for the Telegram report."""
    if all_go_live_gates_pass(gates):
        return "🚀 All gates PASS — ready to go live."

    trend = win_rate_this_week - win_rate_last_week
    win_gate = next((g for g in gates if g.name == "min_win_rate"), None)
    win_rate_passed = win_gate.passed if win_gate else False

    if win_rate_passed:
        failing = [g.name for g in gates if not g.passed]
        return f"Win rate target met — fix: {', '.join(failing)}."

    if win_rate_this_week >= 50 and trend >= 2:
        return "On track for August — win rate climbing toward 55%."

    if trend <= -2:
        return "⚠️ Win rate declining — review recent entries."

    if win_rate_this_week < 40:
        return "⚠️ Win rate stalled — review entry criteria."

    return "Making progress — keep running paper trades."


def format_go_live_telegram_message(
    gates: list[GoLiveGate],
    win_rate_last_100: float,
    win_rate_this_week: float,
    win_rate_last_week: float,
    post_block3_closed: int,
    exit_breakdown_this_week: dict[str, int],
    total_closed: int,
) -> str:
    """Format the weekly go-live readiness report as Telegram HTML.

    Args:
        gates: output of check_go_live_preconditions().
        win_rate_last_100: overall win % for last 100 closed trades.
        win_rate_this_week: win % for trades closed in the last 7 days.
        win_rate_last_week: win % for trades closed 7–14 days ago.
        post_block3_closed: closed trades opened after Block 3 deploy (2026-06-18).
        exit_breakdown_this_week: dict with keys stop_loss, take_profit, max_hold_expired.
        total_closed: total closed paper trades all time.
    """
    gate_icon = {True: "✅", False: "❌"}
    gate_labels = {
        "min_paper_trades": "≥100 closed trades",
        "min_win_rate": "≥55% win rate",
        "positive_avg_pnl": "Positive avg P&amp;L",
        "telegram_send_rate": "Telegram ≥90%",
        "risk_manager_active": "Risk manager active",
    }

    trend_delta = win_rate_this_week - win_rate_last_week
    trend_str = (
        f"+{trend_delta:.1f}%" if trend_delta >= 0 else f"{trend_delta:.1f}%"
    )
    trend_icon = "📈" if trend_delta >= 0 else "📉"

    total_this_week = sum(exit_breakdown_this_week.values())

    def pct(n: int) -> str:
        return f"{n/total_this_week*100:.0f}%" if total_this_week else "—"

    sl = exit_breakdown_this_week.get("stop_loss", 0)
    tp = exit_breakdown_this_week.get("take_profit", 0)
    mh = exit_breakdown_this_week.get("max_hold_expired", 0)

    lines = [
        "📊 <b>Weekly Go-Live Readiness Report</b>",
        "",
        "<b>Gates:</b>",
    ]
    for gate in gates:
        icon = gate_icon[gate.passed]
        label = gate_labels.get(gate.name, gate.name)
        lines.append(f"  {icon} {label}")

    lines += [
        "",
        "<b>Win rate:</b>",
        f"  Last 100 trades: <b>{win_rate_last_100:.1f}%</b> (target 55%)",
        f"  This week:  <b>{win_rate_this_week:.1f}%</b>",
        f"  Last week:  <b>{win_rate_last_week:.1f}%</b>  {trend_icon} {trend_str}",
        "",
        "<b>Post-Block 3 trades (new logic):</b>",
        f"  Closed: <b>{post_block3_closed}</b> / 100 needed",
        "",
        f"<b>Exit reasons this week</b> ({total_this_week} trades):",
        f"  Stop-loss:        {sl:2d}  ({pct(sl)})",
        f"  Take-profit:      {tp:2d}  ({pct(tp)})",
        f"  Max-hold expired: {mh:2d}  ({pct(mh)})",
        "",
        f"<b>Verdict:</b> {_verdict(gates, win_rate_this_week, win_rate_last_week)}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Shadow trade logging
# ---------------------------------------------------------------------------

def _log_shadow_trade(action: str, symbol: str, quantity: float, price: float | None, metadata: dict | None = None) -> dict:
    """Build a shadow trade record for persistence."""
    return {
        "action": action,
        "symbol": symbol,
        "quantity": quantity,
        "price": price,
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata or {},
    }


def persist_shadow_trade(shadow_trade: dict) -> None:
    """Write a shadow trade to the shadow_trades table (best-effort)."""
    from app.config import USE_SUPABASE
    if not USE_SUPABASE:
        logger.info("Shadow trade (no DB): %s", shadow_trade)
        return

    try:
        from app.storage import supabase_store
        supabase_store.insert_shadow_trade(shadow_trade)
    except Exception as exc:
        logger.warning("Failed to persist shadow trade: %s", exc)


# ---------------------------------------------------------------------------
# Binance executor
# ---------------------------------------------------------------------------

class BinanceExecutor:
    """Thin wrapper around python-binance for spot market orders.

    When LIVE_TRADING_ENABLED=false (default): logs what would be ordered
    but places nothing. When shadow mode is enabled, would-be orders are
    written to the shadow_trades table for comparison against paper trades.
    """

    def __init__(self) -> None:
        self._client = None
        self._live = LIVE_TRADING_ENABLED
        self._shadow = SHADOW_MODE_ENABLED

        if self._live:
            self._client = self._init_binance_client()

    def _init_binance_client(self) -> Any:
        """Initialise the python-binance client. Fails hard if keys missing."""
        api_key = os.getenv("BINANCE_API_KEY", "")
        api_secret = os.getenv("BINANCE_API_SECRET", "")

        if not api_key or not api_secret:
            raise RuntimeError(
                "LIVE_TRADING_ENABLED=true but BINANCE_API_KEY or "
                "BINANCE_API_SECRET is not set."
            )

        try:
            from binance.client import Client  # type: ignore[import]
            return Client(api_key, api_secret)
        except ImportError as exc:
            raise RuntimeError(
                "python-binance is not installed. Run: pip install python-binance"
            ) from exc

    def place_market_buy(
        self,
        symbol: str,
        quantity: float,
    ) -> dict:
        """Place a spot market buy order (or log it when disabled)."""
        if self._live and self._client is not None:
            result = self._client.order_market_buy(symbol=symbol, quantity=quantity)
            logger.info("Live market buy placed: %s × %.6f → %s", symbol, quantity, result)
            return result

        logger.info(
            "[DRY-RUN] Would BUY %s × %.6f (live trading disabled).",
            symbol,
            quantity,
        )
        shadow = _log_shadow_trade("market_buy", symbol, quantity, price=None)

        if self._shadow:
            persist_shadow_trade(shadow)

        return shadow

    def place_market_sell(
        self,
        symbol: str,
        quantity: float,
    ) -> dict:
        """Place a spot market sell order (or log it when disabled)."""
        if self._live and self._client is not None:
            result = self._client.order_market_sell(symbol=symbol, quantity=quantity)
            logger.info("Live market sell placed: %s × %.6f → %s", symbol, quantity, result)
            return result

        logger.info(
            "[DRY-RUN] Would SELL %s × %.6f (live trading disabled).",
            symbol,
            quantity,
        )
        shadow = _log_shadow_trade("market_sell", symbol, quantity, price=None)

        if self._shadow:
            persist_shadow_trade(shadow)

        return shadow

    def get_account_balance(self, asset: str = "USDT") -> float:
        """Return free balance for `asset`. Returns 0.0 when live trading disabled."""
        if not self._live or self._client is None:
            logger.info("[DRY-RUN] Returning 0 balance (live trading disabled).")
            return 0.0

        balances = self._client.get_account().get("balances", [])
        for item in balances:
            if item.get("asset") == asset:
                return float(item.get("free", 0))
        return 0.0
