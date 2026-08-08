"""Simulated paper trading engine for alert candidates.

This module only records hypothetical long trades. It uses public candle data
for evaluation and never places orders or touches private exchange APIs.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.binance.client import klines_to_dataframe
from app.config import PAPER_SLIPPAGE_BUDGET_PCT, USE_SUPABASE
from app.exchange.binance_executor import (
    BinanceExecutor,
    evaluate_entry_slippage,
    fetch_real_fill,
)
from app.risk.risk_manager import RiskConfig, compute_position_size, evaluate_trade_risk
from app.storage import supabase_store
from app.trading.strategy_config import (
    PaperTradingStrategy,
    get_default_paper_trading_strategy,
    get_parabolic_paper_strategy,
)
from app.utils.logger import get_logger

PAPER_TRADES_FILE = "data/paper_trades.json"
PAPER_TRADE_EVENTS_FILE = "data/paper_trade_events.json"
# Round-trip fee + liquidity-scaled slippage subtracted from every paper trade's
# gross P&L to get a realistic net P&L. Go-live gates must use NET, never gross.
ROUND_TRIP_FEE_PCT = 0.2
SLIPPAGE_PCT_BY_LIQUIDITY = {
    "excellent": 0.2,
    "strong": 0.2,
    "good": 0.3,
    "thin": 0.8,
    "very thin": 1.5,
}
DEFAULT_SLIPPAGE_PCT = 1.5
PAPER_TRADE_ALLOWED_ALERT_TYPES = {
    "Continuation Alert",
    "Early Pump Alert",
    "Active Breakout Alert",
}
PARABOLIC_WATCH_ALERT_TYPE = "Parabolic Watch Alert"
# Legacy alert type/trade-plan-type from the retired Speculative Early Runner
# lane (folded into the unified Early Pump/Active Breakout/Continuation range
# in Block 3 — its only reason to exist was bypassing the liquidity floor,
# which the real slippage gate now does for every alert type). Kept only so
# reporting modules can still bucket the ~100 historical trades correctly —
# no new trade is ever created with this alert type.
SPECULATIVE_EARLY_RUNNER_ALERT_TYPE = "Speculative Early Runner Alert"
SPECULATIVE_EARLY_RUNNER_TRADE_PLAN_TYPE = "speculative_early_runner"
PARABOLIC_TRADE_PLAN_TYPE = "parabolic_high_risk_paper"
# Aligned to the same 50% threshold that fires the Parabolic Watch Alert
# itself (explosive_mover.py) — previously 40%, which made this "extra" gate
# looser than the trigger instead of stricter.
PARABOLIC_MIN_24H_CHANGE_PCT = 50
MAX_OPEN_PAPER_TRADES_BY_ALERT_TYPE = {
    # No new trade is ever created with this alert type anymore (Block 3
    # retired the lane), but app/analysis/paper_trading_report.py still reads
    # this key when reporting on the ~100 historical trades that used it.
    SPECULATIVE_EARLY_RUNNER_ALERT_TYPE: 5,
    PARABOLIC_WATCH_ALERT_TYPE: 10,
    "Continuation Alert": 10,
}
MAX_TOTAL_OPEN_PAPER_TRADES = 20
# Conviction-based position sizing: the risk-manager's per-trade risk formula
# gives a base size, scaled by a [MIN, MAX] multiplier driven by how strong
# the setup looks (opportunity_score) and how much slippage-budget headroom
# the order book has (tradability_headroom). Opportunity is weighted higher
# since it answers "is this a good setup"; tradability just confirms we can
# actually execute it at the size the opportunity alone would justify.
POSITION_SIZE_MIN_MULTIPLIER = 0.5
POSITION_SIZE_MAX_MULTIPLIER = 1.5
POSITION_SIZE_OPPORTUNITY_WEIGHT = 0.7
POSITION_SIZE_TRADABILITY_WEIGHT = 0.3
MAX_HOLD_EXPIRED_EVENT_NOTES = (
    "Closed stale paper trade because max_hold_hours was reached."
)
logger = get_logger(__name__)


def build_paper_trade_from_alert(
    result: dict,
    strategy: PaperTradingStrategy | None = None,
    position_size_override: float | None = None,
) -> dict:
    """Build a simulated long trade from one alert candidate.

    `position_size_override` is the conviction/volatility-adjusted size from
    `compute_conviction_position_size` — falls back to the strategy's fixed
    `simulated_position_size` when not provided (manual/CLI callers, tests).
    """
    strategy = strategy or get_default_paper_trading_strategy()
    opened_at = _utc_now_iso()
    symbol = str(result.get("symbol") or "UNKNOWN")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    trade_plan = _get_trade_plan(result)

    return {
        "id": f"paper_{symbol}_{timestamp}",
        "alert_id": _first_present(result, "alert_id", "id"),
        "alert_history_id": _first_present(result, "alert_history_id", "alert_id"),
        "source_alert_id": _first_present(result, "source_alert_id", "id"),
        "strategy_name": strategy.name,
        "symbol": symbol,
        "alert_type": _get_alert_type(result),
        "trade_plan_type": _get_trade_plan_type(result, trade_plan),
        "opened_at": opened_at,
        "entry_price": result.get("latest_close"),
        "status": "open",
        "direction": "long",
        "opportunity_score": _get_opportunity_value(result, "opportunity_score"),
        "classification": _get_opportunity_value(result, "classification"),
        "target_bucket": _get_opportunity_value(result, "target_bucket"),
        "continuation_target": _get_continuation_target(result),
        "move_stage": _get_move_stage(result),
        "move_from_recent_low_pct": _get_move_from_recent_low_pct(result),
        "liquidity_label": _get_liquidity_label(result),
        "tradability_score": _get_tradability_score(result),
        "exhaustion_risk_level": _get_exhaustion_risk_level(result),
        "stop_loss_pct": _trade_plan_value(
            trade_plan,
            "stop_loss_pct",
            strategy.stop_loss_pct,
        ),
        "take_profit_1_pct": _trade_plan_value(
            trade_plan,
            "take_profit_1_pct",
            strategy.take_profit_1_pct,
        ),
        "take_profit_2_pct": _trade_plan_value(
            trade_plan,
            "take_profit_2_pct",
            strategy.take_profit_2_pct,
        ),
        "take_profit_3_pct": _trade_plan_value(
            trade_plan,
            "take_profit_3_pct",
            strategy.take_profit_3_pct,
        ),
        "max_hold_hours": _trade_plan_value(
            trade_plan,
            "max_hold_hours",
            _score_based_max_hold_hours(
                _get_opportunity_value(result, "opportunity_score"), strategy
            ),
        ),
        "simulated_position_size": (
            position_size_override
            if position_size_override is not None
            else strategy.simulated_position_size
        ),
        "peak_price": result.get("latest_close"),
        "trailing_stop_price": None,
        "partial_tp1_hit": False,
        "partial_tp2_hit": False,
        "partial_tp1_price": None,
        "partial_tp2_price": None,
        "blended_pnl_pct": None,
    }


def should_create_paper_trade(
    result: dict,
    strategy: PaperTradingStrategy | None = None,
) -> tuple[bool, str]:
    """Return whether an alert candidate qualifies for a simulated trade."""
    strategy = strategy or get_default_paper_trading_strategy()
    alert_type = _get_alert_type(result)

    if alert_type == PARABOLIC_WATCH_ALERT_TYPE:
        return False, "Parabolic Watch Alert is not eligible for paper trading."

    if alert_type not in PAPER_TRADE_ALLOWED_ALERT_TYPES:
        return False, f"{alert_type} is not eligible for paper trading."

    opportunity_score = _safe_float(_get_opportunity_value(result, "opportunity_score"))

    if opportunity_score < strategy.minimum_opportunity_score:
        return (
            False,
            f"Opportunity score is below {strategy.minimum_opportunity_score}.",
        )

    move_pct = _safe_float(_get_move_from_recent_low_pct(result), default=None)

    if (
        move_pct is None
        or move_pct < strategy.min_move_from_recent_low_pct
        or move_pct > strategy.max_move_from_recent_low_pct
    ):
        return False, _move_range_reason(strategy)

    exhaustion_level = str(_get_exhaustion_risk_level(result) or "").strip()

    if not strategy.allow_high_exhaustion and exhaustion_level.lower() == "high":
        return False, "Exhaustion risk is High."

    return True, "Paper trade eligible."


def _move_range_reason(strategy: PaperTradingStrategy) -> str:
    """Build a human-readable move-window rejection reason for a strategy."""
    if strategy.max_move_from_recent_low_pct == float("inf"):
        return (
            "Move from recent low must be at least "
            f"{strategy.min_move_from_recent_low_pct:g}%."
        )

    return (
        "Move from recent low must be between "
        f"{strategy.min_move_from_recent_low_pct:g}% and "
        f"{strategy.max_move_from_recent_low_pct:g}%."
    )


def should_create_parabolic_paper_trade(
    result: dict,
    strategy: PaperTradingStrategy | None = None,
) -> tuple[bool, str]:
    """Return whether a Parabolic Watch Alert qualifies for paper-only testing."""
    strategy = strategy or get_parabolic_paper_strategy()
    alert_type = _get_alert_type(result)

    if alert_type != PARABOLIC_WATCH_ALERT_TYPE:
        return False, f"{alert_type} is not a Parabolic Watch Alert."

    opportunity_score = _safe_float(
        _get_opportunity_value(result, "opportunity_score"),
        default=None,
    )

    if (
        opportunity_score is None
        or opportunity_score < strategy.minimum_opportunity_score
    ):
        return (
            False,
            f"Opportunity score is below {strategy.minimum_opportunity_score}.",
        )

    move_pct = _safe_float(_get_move_from_recent_low_pct(result), default=None)

    if (
        move_pct is None
        or move_pct < strategy.min_move_from_recent_low_pct
        or move_pct > strategy.max_move_from_recent_low_pct
    ):
        return False, _move_range_reason(strategy)

    exhaustion_level = str(_get_exhaustion_risk_level(result) or "").strip()

    if not strategy.allow_high_exhaustion and exhaustion_level.lower() == "high":
        return False, "Exhaustion risk is High."

    change_24h = _safe_float(
        _get_recent_price_change(result, "change_24h_pct"),
        default=None,
    )

    if change_24h is None or change_24h < PARABOLIC_MIN_24H_CHANGE_PCT:
        return (
            False,
            f"24h change is below {PARABOLIC_MIN_24H_CHANGE_PCT:g}%.",
        )

    if not _has_parabolic_reacceleration(result):
        return (
            False,
            (
                "No parabolic re-acceleration trigger: needs 2h volume "
                "acceleration >= 2x, 1h change >= 2%, 2h change >= 5%, "
                "or 4h change >= 10%."
            ),
        )

    return True, "Parabolic paper trade eligible."


def can_create_more_trades_for_alert_type(
    alert_type: str,
    open_trades: list[dict],
) -> tuple[bool, str]:
    """Return whether concentration limits allow another open paper trade."""
    active_open_trades = [
        trade
        for trade in open_trades
        if isinstance(trade, dict)
        and str(trade.get("status", "open")).lower() == "open"
    ]

    if len(active_open_trades) >= MAX_TOTAL_OPEN_PAPER_TRADES:
        return False, "Total open paper trade limit reached."

    limit = MAX_OPEN_PAPER_TRADES_BY_ALERT_TYPE.get(alert_type)

    if limit is None:
        return True, "Paper trade concentration limit allows this alert type."

    current_count = sum(
        1
        for trade in active_open_trades
        if str(trade.get("alert_type") or "") == alert_type
    )

    if current_count >= limit:
        return False, f"Open trade limit reached for {alert_type}."

    return True, "Paper trade concentration limit allows this alert type."


def create_paper_trades_from_alerts(
    alert_candidates: list[dict],
    strategy: PaperTradingStrategy | None = None,
    risk_config: RiskConfig | None = None,
) -> list[dict]:
    """Create paper trades and return one structured decision per alert."""
    strategy = strategy or get_default_paper_trading_strategy()
    decisions = []
    open_trades = _get_open_paper_trades()
    closed_trades_today = _get_closed_paper_trades_today()
    open_trade_symbols = {
        str(trade.get("symbol"))
        for trade in open_trades
        if trade.get("symbol") and trade.get("status") == "open"
    }

    for candidate in alert_candidates:
        alert_type = _get_alert_type(candidate)
        selected_strategy = strategy
        eligible = False
        reason = "Paper trade skipped."
        candidate_for_trade = candidate

        if alert_type == PARABOLIC_WATCH_ALERT_TYPE:
            selected_strategy = get_parabolic_paper_strategy()
            eligible, reason = should_create_parabolic_paper_trade(
                candidate,
                selected_strategy,
            )

            if eligible:
                candidate_for_trade = _with_parabolic_trade_plan(
                    candidate,
                    selected_strategy,
                    reason,
                )
        else:
            eligible, reason = should_create_paper_trade(candidate, strategy)

        position_size_usd = None

        if eligible:
            stop_loss_pct = float(selected_strategy.stop_loss_pct or -10)
            opportunity_score = _get_opportunity_value(
                candidate_for_trade, "opportunity_score"
            )
            position_size_usd, size_reason = compute_conviction_position_size(
                candidate_for_trade, stop_loss_pct, opportunity_score, risk_config
            )

            if position_size_usd is None:
                eligible = False
                reason = size_reason
            else:
                hard_gate_ok, hard_gate_reason = _meets_hard_trade_gates(
                    candidate_for_trade, position_size_usd
                )

                if not hard_gate_ok:
                    eligible = False
                    reason = hard_gate_reason

        symbol = str(candidate.get("symbol") or "UNKNOWN")
        trade_plan = _get_trade_plan(candidate_for_trade)
        trade_plan_type = _get_trade_plan_type(candidate_for_trade, trade_plan)
        decision = _build_paper_trade_decision(
            candidate,
            eligible=eligible,
            decision="created" if eligible else "ineligible",
            reason=reason,
            strategy=selected_strategy,
            trade_plan_type=trade_plan_type,
        )

        if not eligible:
            _persist_paper_trade_decision(decision)
            _update_alert_paper_trade_status(decision)
            decisions.append(decision)
            continue

        concentration_ok, concentration_reason = (
            can_create_more_trades_for_alert_type(alert_type, open_trades)
        )

        if not concentration_ok:
            decision.update(
                {
                    "paper_trade_created": False,
                    "paper_trade_id": None,
                    "decision": "skipped",
                    "eligible": False,
                    "reason": concentration_reason,
                }
            )
            _persist_paper_trade_decision(decision)
            _update_alert_paper_trade_status(decision)
            decisions.append(decision)
            continue

        if symbol in open_trade_symbols:
            decision.update(
                {
                    "paper_trade_created": False,
                    "paper_trade_id": None,
                    "decision": "duplicate",
                    "reason": f"Duplicate open paper trade exists for {symbol}.",
                }
            )
            _persist_paper_trade_decision(decision)
            _update_alert_paper_trade_status(decision)
            decisions.append(decision)
            continue

        # Portfolio-level risk gates (position limit, capital cap, drawdown, correlation).
        risk_decision = evaluate_trade_risk(
            symbol=symbol,
            stop_loss_pct=float(selected_strategy.stop_loss_pct or -10),
            open_trades=open_trades,
            closed_trades_today=closed_trades_today,
            config=risk_config,
        )
        if not risk_decision.allowed:
            decision.update(
                {
                    "paper_trade_created": False,
                    "paper_trade_id": None,
                    "decision": "skipped",
                    "eligible": False,
                    "reason": f"Risk gate blocked: {risk_decision.reason}",
                }
            )
            _persist_paper_trade_decision(decision)
            _update_alert_paper_trade_status(decision)
            decisions.append(decision)
            continue

        trade = build_paper_trade_from_alert(
            candidate_for_trade,
            selected_strategy,
            position_size_override=position_size_usd,
        )
        _insert_paper_trade(trade)
        _insert_paper_trade_event(_build_trade_event(trade, "opened"))
        _log_shadow_trade_open(trade)
        open_trade_symbols.add(symbol)
        open_trades.append(trade)
        decision.update(
            {
                "paper_trade_created": True,
                "paper_trade_id": trade.get("id"),
                "decision": "created",
                "reason": reason,
            }
        )
        _persist_paper_trade_decision(decision)
        _update_alert_paper_trade_status(decision)
        decisions.append(decision)

    return decisions


def _build_paper_trade_decision(
    result: dict,
    eligible: bool,
    decision: str,
    reason: str,
    strategy: PaperTradingStrategy,
    trade_plan_type: str | None,
) -> dict:
    """Build a structured paper-trade decision for one alert candidate."""
    alert_history_id = _first_present(result, "alert_history_id", "alert_id")

    return {
        "symbol": str(result.get("symbol") or "UNKNOWN"),
        "alert_type": _get_alert_type(result),
        "alert_history_id": alert_history_id,
        "paper_trade_created": False,
        "paper_trade_id": None,
        "decision": decision,
        "eligible": bool(eligible),
        "reason": reason,
        "strategy_name": strategy.name if strategy else None,
        "trade_plan_type": trade_plan_type,
        "metadata": {
            "source_alert_id": _first_present(result, "source_alert_id", "id"),
            "opportunity_score": _get_opportunity_value(
                result,
                "opportunity_score",
            ),
            "scan_run_id": result.get("scan_run_id"),
            "trade_plan": _get_trade_plan(result),
        },
    }


def _persist_paper_trade_decision(decision: dict) -> None:
    """Persist a paper-trade decision when Supabase is enabled."""
    if not USE_SUPABASE:
        return

    supabase_store.insert_paper_trade_decision(decision)


def _update_alert_paper_trade_status(decision: dict) -> None:
    """Update alert_history with the paper-trade decision when available."""
    if not USE_SUPABASE:
        return

    supabase_store.update_alert_paper_trade_status(
        decision.get("alert_history_id"),
        bool(decision.get("paper_trade_created")),
        decision.get("paper_trade_id"),
        None if decision.get("paper_trade_created") else decision.get("reason"),
    )


def evaluate_open_paper_trade(trade: dict, candles_df) -> dict:
    """Evaluate one open paper trade against market candles.

    Returns a dict with exit fields when the trade closes, or a tracking-state
    dict (peak_price, trailing_stop_price, partial TP flags) when still open.
    """
    entry_price = _safe_float(trade.get("entry_price"), default=None)

    if entry_price is None or entry_price <= 0:
        return {"status": "open"}

    opened_at = _parse_timestamp(trade.get("opened_at"))

    if opened_at is None:
        return {"status": "open"}

    post_open_candles = _candles_after_opened_at(candles_df, opened_at)

    if post_open_candles.empty:
        return {"status": "open"}

    initial_stop_pct = trade.get("stop_loss_pct", -10)
    initial_stop_price = _price_at_pct(entry_price, initial_stop_pct)
    take_profit_1_price = _price_at_pct(entry_price, trade.get("take_profit_1_pct", 8))
    take_profit_2_price = _price_at_pct(entry_price, trade.get("take_profit_2_pct", 15))
    take_profit_3_price = _price_at_pct(entry_price, trade.get("take_profit_3_pct", 20))
    max_hold_hours = _safe_float(trade.get("max_hold_hours"), default=48) or 48
    expires_at = opened_at + timedelta(hours=max_hold_hours)

    # Trailing stop configuration (defaults match strategy_config defaults).
    breakeven_trigger_pct = 10.0
    activate_trigger_pct = 25.0
    trail_pct = 15.0

    # Partial-exit state (persisted between scan runs via trade dict).
    partial_tp1_hit = bool(trade.get("partial_tp1_hit", False))
    partial_tp1_price = _safe_float(trade.get("partial_tp1_price"), default=None)
    partial_tp2_hit = bool(trade.get("partial_tp2_hit", False))
    partial_tp2_price = _safe_float(trade.get("partial_tp2_price"), default=None)

    # Running state — seed from persisted values so we don't reset each scan.
    peak_price = _safe_float(trade.get("peak_price"), default=entry_price) or entry_price
    current_stop = _safe_float(trade.get("trailing_stop_price"), default=None)
    if current_stop is None or current_stop <= 0:
        current_stop = initial_stop_price

    tracking_changed = False

    for _index, candle in post_open_candles.iterrows():
        candle_time = _row_timestamp(candle)

        if candle_time is not None and candle_time > expires_at:
            break

        low = _safe_float(candle.get("low"), default=None)
        high = _safe_float(candle.get("high"), default=None)

        # Check TP3 first (optimistic candle ordering: assume high before low).
        # Also register lower partial TPs that would have been crossed en route.
        if high is not None and high >= take_profit_3_price:
            new_peak = max(peak_price, high)
            if not partial_tp1_hit and high >= take_profit_1_price:
                partial_tp1_hit = True
                partial_tp1_price = take_profit_1_price
            if partial_tp1_hit and not partial_tp2_hit and high >= take_profit_2_price:
                partial_tp2_hit = True
                partial_tp2_price = take_profit_2_price
            return _build_blended_close(
                trade, take_profit_3_price, "take_profit_3", candle_time,
                partial_tp1_hit, partial_tp1_price,
                partial_tp2_hit, partial_tp2_price,
                new_peak, current_stop,
            )

        # Update running peak.
        if high is not None and high > peak_price:
            peak_price = high
            tracking_changed = True

        # Update trailing stop based on new peak.
        gain_pct = (peak_price - entry_price) / entry_price * 100

        if gain_pct >= activate_trigger_pct:
            # Trail stop at trail_pct% below running peak.
            new_stop = peak_price * (1 - trail_pct / 100)
            if new_stop > current_stop:
                current_stop = new_stop
                tracking_changed = True
        elif gain_pct >= breakeven_trigger_pct:
            # Move stop up to breakeven (entry price).
            if entry_price > current_stop:
                current_stop = entry_price
                tracking_changed = True

        # Check stop-loss (initial or trailing) after TP3 has been checked.
        if low is not None and low <= current_stop:
            return _build_blended_close(
                trade, current_stop, "stop_loss", candle_time,
                partial_tp1_hit, partial_tp1_price,
                partial_tp2_hit, partial_tp2_price,
                peak_price, current_stop,
            )

        # Register partial TP1 (does not close trade).
        if not partial_tp1_hit and high is not None and high >= take_profit_1_price:
            partial_tp1_hit = True
            partial_tp1_price = take_profit_1_price
            tracking_changed = True

        # Register partial TP2 (requires TP1 to have been hit; does not close).
        if (
            partial_tp1_hit
            and not partial_tp2_hit
            and high is not None
            and high >= take_profit_2_price
        ):
            partial_tp2_hit = True
            partial_tp2_price = take_profit_2_price
            tracking_changed = True

    # Max hold expiry check.
    latest_candle = post_open_candles.iloc[-1]
    latest_time = _row_timestamp(latest_candle)

    if latest_time is not None and latest_time >= expires_at:
        latest_close = _safe_float(latest_candle.get("close"), default=None)

        if latest_close is None:
            return {"status": "open"}

        return _build_blended_close(
            trade, latest_close, "max_hold_expired", latest_time,
            partial_tp1_hit, partial_tp1_price,
            partial_tp2_hit, partial_tp2_price,
            peak_price, current_stop,
        )

    # Still open — persist tracking state if it changed.
    if tracking_changed:
        return {
            "status": "open",
            "peak_price": round(peak_price, 8),
            "trailing_stop_price": round(current_stop, 8),
            "partial_tp1_hit": partial_tp1_hit,
            "partial_tp2_hit": partial_tp2_hit,
            "partial_tp1_price": round(partial_tp1_price, 8) if partial_tp1_price else None,
            "partial_tp2_price": round(partial_tp2_price, 8) if partial_tp2_price else None,
        }

    return {"status": "open"}


def update_open_paper_trades(client) -> dict:
    """Evaluate all open paper trades and persist any closures."""
    open_trades = _get_open_paper_trades()
    closed_stop_loss = 0
    closed_take_profit = 0
    closed_max_hold = 0
    still_open = 0
    errors = 0

    for trade in open_trades:
        symbol = trade.get("symbol")

        if not symbol:
            still_open += 1
            errors += 1
            continue

        try:
            klines = client.get_klines(symbol, "15m", 500)
            candles = klines_to_dataframe(klines)
            updates = _build_stale_paper_trade_updates(trade, candles)

            if updates is None:
                updates = evaluate_open_paper_trade(trade, candles)
        except Exception as exc:
            logger.warning(
                "Failed to update paper trade for %s (id=%s): %s",
                symbol,
                trade.get("id"),
                exc,
            )
            still_open += 1
            errors += 1
            continue

        if updates.get("status") == "closed":
            _update_paper_trade(str(trade.get("id")), updates)
            closed_trade = {**trade, **updates}
            _insert_paper_trade_event(_build_close_event(closed_trade))
            _log_shadow_trade_close(closed_trade)
            _apply_real_slippage_if_available(closed_trade)
            exit_reason = str(updates.get("exit_reason") or "")

            if exit_reason == "max_hold_expired":
                logger.info("Closed stale paper trade due to max hold: %s", symbol)
                closed_max_hold += 1
            elif exit_reason.startswith("take_profit"):
                closed_take_profit += 1
            elif exit_reason == "stop_loss":
                closed_stop_loss += 1
        elif len(updates) > 1:
            # Intermediate tracking state update (peak price, partial TPs, trailing stop).
            _update_paper_trade(str(trade.get("id")), updates)
            still_open += 1
        else:
            still_open += 1

    closed_trades = closed_stop_loss + closed_take_profit + closed_max_hold

    return {
        "checked": len(open_trades),
        "open_trades_checked": len(open_trades),
        "closed_trades": closed_trades,
        "closed_stop_loss": closed_stop_loss,
        "closed_take_profit": closed_take_profit,
        "closed_max_hold": closed_max_hold,
        "still_open": still_open,
        "errors": errors,
    }


def _insert_paper_trade(trade: dict) -> None:
    """Persist a paper trade to the configured backend."""
    if USE_SUPABASE:
        supabase_store.insert_paper_trade(trade)
        return

    trades = _load_json_list(PAPER_TRADES_FILE)

    if any(existing.get("id") == trade.get("id") for existing in trades):
        return

    trades.append(trade)
    _save_json_list(PAPER_TRADES_FILE, trades)


def _get_open_paper_trades() -> list[dict]:
    """Load open paper trades from the configured backend."""
    if USE_SUPABASE:
        return supabase_store.get_open_paper_trades()

    return [
        trade
        for trade in _load_json_list(PAPER_TRADES_FILE)
        if trade.get("status") == "open"
    ]


def _get_closed_paper_trades_today() -> list[dict]:
    """Load paper trades closed in the last 24 h (for daily drawdown gate)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    if USE_SUPABASE:
        try:
            return supabase_store.get_closed_paper_trades_since(cutoff)
        except Exception:
            return []

    return [
        trade
        for trade in _load_json_list(PAPER_TRADES_FILE)
        if trade.get("status") == "closed"
        and str(trade.get("closed_at") or "") >= cutoff
    ]


def _update_paper_trade(trade_id: str, updates: dict) -> None:
    """Update a paper trade in the configured backend."""
    if USE_SUPABASE:
        supabase_store.update_paper_trade(trade_id, updates)
        return

    trades = _load_json_list(PAPER_TRADES_FILE)

    for trade in trades:
        if trade.get("id") == trade_id:
            trade.update(updates)
            break

    _save_json_list(PAPER_TRADES_FILE, trades)


def _insert_paper_trade_event(event: dict) -> None:
    """Persist a paper trade event to the configured backend."""
    if USE_SUPABASE:
        supabase_store.insert_paper_trade_event(event)
        return

    events = _load_json_list(PAPER_TRADE_EVENTS_FILE)

    if any(existing.get("id") == event.get("id") for existing in events):
        return

    events.append(event)
    _save_json_list(PAPER_TRADE_EVENTS_FILE, events)


def _shadow_quantity(trade: dict) -> float | None:
    """Return a shadow-order quantity sized from the trade's simulated position."""
    entry_price = _safe_float(trade.get("entry_price"), default=None)

    if entry_price is None or entry_price <= 0:
        return None

    position_size = _safe_float(trade.get("simulated_position_size"), default=50) or 50

    return position_size / entry_price


def _log_shadow_trade_open(trade: dict) -> None:
    """Mirror a paper-trade open into shadow_trades with the real order-book price.

    Lets us compare the paper fill price against what a live order would
    actually have filled at, at the moment the trade opened.
    """
    quantity = _shadow_quantity(trade)

    if quantity is None:
        return

    try:
        BinanceExecutor().place_market_buy(
            str(trade.get("symbol") or ""),
            quantity,
            price=_safe_float(trade.get("entry_price"), default=None),
            metadata={
                "paper_trade_id": trade.get("id"),
                "alert_history_id": trade.get("alert_history_id"),
                "liquidity_label": trade.get("liquidity_label"),
            },
        )
    except Exception as exc:
        logger.warning(
            "Failed to log shadow open trade for %s: %s", trade.get("symbol"), exc
        )


def _log_shadow_trade_close(trade: dict) -> None:
    """Mirror a paper-trade close into shadow_trades with the real order-book price."""
    quantity = _shadow_quantity(trade)
    exit_price = _safe_float(trade.get("exit_price"), default=None)

    if quantity is None or exit_price is None or exit_price <= 0:
        return

    try:
        BinanceExecutor().place_market_sell(
            str(trade.get("symbol") or ""),
            quantity,
            price=exit_price,
            metadata={
                "paper_trade_id": trade.get("id"),
                "alert_history_id": trade.get("alert_history_id"),
                "exit_reason": trade.get("exit_reason"),
                "liquidity_label": trade.get("liquidity_label"),
            },
        )
    except Exception as exc:
        logger.warning(
            "Failed to log shadow close trade for %s: %s", trade.get("symbol"), exc
        )


def load_paper_trades(limit: int | None = None) -> list[dict]:
    """Load persisted paper trades from the configured backend."""
    if USE_SUPABASE:
        return supabase_store.load_paper_trades(limit=limit)

    trades = _load_json_list(PAPER_TRADES_FILE)

    if limit is not None:
        return trades[:max(0, int(limit))]

    return trades


def load_all_paper_trades(limit: int | None = None) -> list[dict]:
    """Load all persisted paper trades from the configured backend."""
    return load_paper_trades(limit=limit)


def _build_trade_event(trade: dict, event_type: str) -> dict:
    """Build a JSON-friendly paper trade event."""
    occurred_at = (
        trade.get("closed_at")
        if event_type in {"closed", "max_hold_expired"}
        else trade.get("opened_at")
    ) or _utc_now_iso()

    return {
        "id": f"event_{trade.get('id')}_{event_type}",
        "trade_id": trade.get("id"),
        "symbol": trade.get("symbol"),
        "type": event_type,
        "occurred_at": occurred_at,
        "details": {
            "entry_price": trade.get("entry_price"),
            "exit_price": trade.get("exit_price"),
            "exit_reason": trade.get("exit_reason"),
            "pnl_pct": trade.get("pnl_pct"),
            "pnl_amount": trade.get("pnl_amount"),
        },
    }


def _build_close_event(trade: dict) -> dict:
    """Build the correct close event for a paper trade closure."""
    if trade.get("exit_reason") != "max_hold_expired":
        return _build_trade_event(trade, "closed")

    event = _build_trade_event(trade, "max_hold_expired")
    event["notes"] = MAX_HOLD_EXPIRED_EVENT_NOTES
    return event


def _build_blended_close(
    trade: dict,
    final_price: float,
    exit_reason: str,
    closed_at: datetime | None,
    partial_tp1_hit: bool,
    partial_tp1_price: float | None,
    partial_tp2_hit: bool,
    partial_tp2_price: float | None,
    peak_price: float,
    trailing_stop_price: float,
) -> dict:
    """Build close-update fields with blended partial-exit P&L."""
    entry_price = float(trade["entry_price"])
    position_size = _safe_float(trade.get("simulated_position_size"), default=50) or 50

    tp1_frac = 0.5
    tp2_frac = 0.3

    # Build weighted blended exit price.
    weighted = 0.0
    allocated = 0.0

    if partial_tp1_hit and partial_tp1_price:
        weighted += tp1_frac * float(partial_tp1_price)
        allocated += tp1_frac

    if partial_tp2_hit and partial_tp2_price:
        weighted += tp2_frac * float(partial_tp2_price)
        allocated += tp2_frac

    remaining = 1.0 - allocated
    weighted += remaining * float(final_price)

    blended_pnl_pct = (weighted - entry_price) / entry_price * 100
    net_pnl_pct = _net_pnl_pct(blended_pnl_pct, trade.get("liquidity_label"))

    return {
        "status": "closed",
        "closed_at": _format_timestamp(closed_at) if closed_at else _utc_now_iso(),
        "exit_price": round(float(final_price), 8),
        "exit_reason": exit_reason,
        "pnl_pct": round(blended_pnl_pct, 2),
        "pnl_amount": round(position_size * (blended_pnl_pct / 100), 2),
        "blended_pnl_pct": round(blended_pnl_pct, 2),
        "gross_pnl_pct": round(blended_pnl_pct, 2),
        "net_pnl_pct": round(net_pnl_pct, 2),
        "net_pnl_amount": round(position_size * (net_pnl_pct / 100), 2),
        "peak_price": round(peak_price, 8),
        "trailing_stop_price": round(trailing_stop_price, 8),
        "partial_tp1_hit": partial_tp1_hit,
        "partial_tp2_hit": partial_tp2_hit,
        "partial_tp1_price": round(partial_tp1_price, 8) if partial_tp1_price else None,
        "partial_tp2_price": round(partial_tp2_price, 8) if partial_tp2_price else None,
    }


def _build_close_updates(
    trade: dict,
    exit_price: float,
    exit_reason: str,
    closed_at: datetime | None,
) -> dict:
    """Build update fields for a closed paper trade (simple, no partial TPs)."""
    entry_price = float(trade["entry_price"])
    pnl_pct = ((exit_price - entry_price) / entry_price) * 100
    net_pnl_pct = _net_pnl_pct(pnl_pct, trade.get("liquidity_label"))
    position_size = _safe_float(trade.get("simulated_position_size"), default=50) or 50

    return {
        "status": "closed",
        "closed_at": _format_timestamp(closed_at) if closed_at else _utc_now_iso(),
        "exit_price": round(float(exit_price), 8),
        "exit_reason": exit_reason,
        "pnl_pct": round(pnl_pct, 2),
        "pnl_amount": round(position_size * (pnl_pct / 100), 2),
        "gross_pnl_pct": round(pnl_pct, 2),
        "net_pnl_pct": round(net_pnl_pct, 2),
        "net_pnl_amount": round(position_size * (net_pnl_pct / 100), 2),
    }


def _net_pnl_pct(
    gross_pnl_pct: float,
    liquidity_label: Any,
    real_slippage_pct: float | None = None,
) -> float:
    """Subtract round-trip fees and slippage from a gross P&L.

    Uses real order-book-measured slippage when available (see
    `_real_slippage_pct_for_trade`); otherwise falls back to the flat
    liquidity-tiered estimate.
    """
    if real_slippage_pct is not None:
        slippage_pct = real_slippage_pct
    else:
        slippage_pct = SLIPPAGE_PCT_BY_LIQUIDITY.get(
            str(liquidity_label or "").strip().lower(),
            DEFAULT_SLIPPAGE_PCT,
        )
    return gross_pnl_pct - ROUND_TRIP_FEE_PCT - slippage_pct


def _real_slippage_pct_for_trade(paper_trade_id: str | None) -> float | None:
    """Return real measured round-trip slippage (%) from shadow_trades, or None.

    Sums adverse slippage on both legs: the open (buy — adverse means paying
    more than the signal price) and the close (sell — adverse means receiving
    less). Returns None when no real fill data exists yet (JSON backend,
    shadow persistence failure, or the close leg hasn't been logged yet), so
    callers fall back to the flat liquidity-tiered estimate.
    """
    if not paper_trade_id or not USE_SUPABASE:
        return None

    try:
        shadow_trades = supabase_store.get_shadow_trades_for_paper_trade(paper_trade_id)
    except Exception as exc:
        logger.warning(
            "Failed to load shadow trades for %s: %s", paper_trade_id, exc
        )
        return None

    total_slippage_pct = 0.0
    found_any = False

    for shadow_trade in shadow_trades:
        metadata = shadow_trade.get("metadata") or {}
        signal_price = _safe_float(metadata.get("signal_price"), default=None)
        real_fill_price = _safe_float(metadata.get("real_fill_price"), default=None)

        if signal_price is None or real_fill_price is None or signal_price <= 0:
            continue

        found_any = True
        action = str(shadow_trade.get("action") or "")

        if action == "market_buy":
            total_slippage_pct += max(
                0.0, (real_fill_price - signal_price) / signal_price * 100
            )
        elif action == "market_sell":
            total_slippage_pct += max(
                0.0, (signal_price - real_fill_price) / signal_price * 100
            )

    return total_slippage_pct if found_any else None


def _apply_real_slippage_if_available(closed_trade: dict) -> None:
    """Best-effort: recompute net_pnl_pct from real measured slippage.

    Must run after both shadow-trade legs (open + close) are logged. When
    real fill data isn't available (JSON backend, shadow persistence
    failure, pre-Block-2 rows), the trade keeps the flat-estimate net_pnl_pct
    it was closed with — this never blocks or fails a trade close.
    """
    real_slippage_pct = _real_slippage_pct_for_trade(closed_trade.get("id"))

    if real_slippage_pct is None:
        return

    gross_pnl_pct = _safe_float(
        closed_trade.get("blended_pnl_pct")
        if closed_trade.get("blended_pnl_pct") is not None
        else closed_trade.get("pnl_pct"),
        default=None,
    )

    if gross_pnl_pct is None:
        return

    net_pnl_pct = _net_pnl_pct(
        gross_pnl_pct, closed_trade.get("liquidity_label"), real_slippage_pct
    )
    position_size = (
        _safe_float(closed_trade.get("simulated_position_size"), default=50) or 50
    )

    try:
        _update_paper_trade(
            str(closed_trade.get("id")),
            {
                "net_pnl_pct": round(net_pnl_pct, 2),
                "net_pnl_amount": round(position_size * (net_pnl_pct / 100), 2),
            },
        )
    except Exception as exc:
        logger.warning(
            "Failed to apply real slippage to paper trade %s: %s",
            closed_trade.get("id"),
            exc,
        )


def _build_stale_paper_trade_updates(trade: dict, candles_df) -> dict | None:
    """Build forced max-hold close updates using the latest available close."""
    if not _is_paper_trade_past_max_hold(trade):
        return None

    if _safe_float(trade.get("entry_price"), default=None) is None:
        return None

    latest_candle = _latest_available_candle(candles_df)

    if latest_candle is None:
        return None

    latest_close = _safe_float(latest_candle.get("close"), default=None)

    if latest_close is None:
        return None

    closed_at = datetime.now(timezone.utc)

    return _build_close_updates(
        trade,
        latest_close,
        "max_hold_expired",
        closed_at,
    )


def _is_paper_trade_past_max_hold(trade: dict) -> bool:
    """Return whether an open paper trade has exceeded its max hold window."""
    opened_at = _parse_timestamp(trade.get("opened_at"))

    if opened_at is None:
        return False

    max_hold_hours = _safe_float(trade.get("max_hold_hours"), default=48) or 48
    expires_at = opened_at + timedelta(hours=max_hold_hours)

    return datetime.now(timezone.utc) >= expires_at


def _latest_available_candle(candles_df):
    """Return the newest candle row available from a candle DataFrame."""
    if candles_df is None or candles_df.empty:
        return None

    candles = candles_df.copy()
    time_column = "open_time" if "open_time" in candles.columns else "close_time"

    if time_column in candles.columns:
        candle_times = pd.to_datetime(candles[time_column], utc=True, errors="coerce")
        candles = candles.assign(_paper_trade_time=candle_times)
        candles = candles.sort_values("_paper_trade_time")

    return candles.iloc[-1]


def _candles_after_opened_at(candles_df, opened_at: datetime) -> pd.DataFrame:
    """Return candles after the trade opened, sorted oldest first."""
    if candles_df is None or candles_df.empty:
        return pd.DataFrame()

    candles = candles_df.copy()
    time_column = "open_time" if "open_time" in candles.columns else "close_time"

    if time_column not in candles.columns:
        return candles

    candle_times = pd.to_datetime(candles[time_column], utc=True, errors="coerce")
    candles = candles[candle_times >= opened_at]
    candles = candles.assign(_paper_trade_time=candle_times[candle_times >= opened_at])

    return candles.sort_values("_paper_trade_time")


def _row_timestamp(row) -> datetime | None:
    """Read a candle row timestamp as UTC."""
    value = row.get("_paper_trade_time")

    if value is None or pd.isna(value):
        value = row.get("open_time", row.get("close_time"))

    return _parse_timestamp(value)


def _price_at_pct(entry_price: float, pct: Any) -> float:
    """Return a price offset from entry by a percentage."""
    pct_float = _safe_float(pct, default=0) or 0
    return entry_price * (1 + (pct_float / 100))


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse timestamps from strings, pandas values, or datetimes as UTC."""
    if value is None:
        return None

    try:
        parsed = pd.to_datetime(value, utc=True)
    except (TypeError, ValueError):
        return None

    if pd.isna(parsed):
        return None

    return parsed.to_pydatetime()


def _format_timestamp(value: datetime) -> str:
    """Format a timestamp as an ISO UTC string."""
    return value.astimezone(timezone.utc).isoformat()


def _get_opportunity_value(result: dict, key: str) -> Any:
    """Read values from nested opportunity data with top-level fallback."""
    opportunity = result.get("opportunity") or {}

    if opportunity.get(key) is not None:
        return opportunity.get(key)

    return result.get(key)


def _get_alert_type(result: dict) -> str:
    """Read the alert type, defaulting old alert payloads to continuation."""
    if result.get("alert_type") is not None:
        return str(result.get("alert_type"))

    explosive_mover = result.get("explosive_mover") or {}

    if explosive_mover.get("should_alert"):
        return str(explosive_mover.get("alert_type", "Explosive Mover Alert"))

    return "Continuation Alert"


def _get_trade_plan(result: dict) -> dict:
    """Return a trade plan dict when present."""
    trade_plan = result.get("trade_plan")

    if isinstance(trade_plan, dict):
        return trade_plan

    return {}


def _trade_plan_value(trade_plan: dict, key: str, fallback: Any) -> Any:
    """Read a trade-plan value with strategy fallback."""
    if trade_plan.get(key) is not None:
        return trade_plan.get(key)

    return fallback


def _score_based_max_hold_hours(score: Any, strategy: PaperTradingStrategy) -> int:
    """Return the appropriate max hold window based on opportunity score."""
    try:
        score_int = int(score or 0)
    except (TypeError, ValueError):
        score_int = 0

    if score_int >= strategy.high_score_threshold:
        return strategy.high_score_max_hold_hours

    return strategy.max_hold_hours


def _get_trade_plan_type(result: dict, trade_plan: dict) -> str | None:
    """Read or infer the trade-plan type stored with paper trades."""
    if trade_plan.get("trade_plan_type"):
        return str(trade_plan.get("trade_plan_type"))

    alert_type = _get_alert_type(result)

    if alert_type == PARABOLIC_WATCH_ALERT_TYPE:
        return PARABOLIC_TRADE_PLAN_TYPE

    if alert_type == SPECULATIVE_EARLY_RUNNER_ALERT_TYPE:
        return SPECULATIVE_EARLY_RUNNER_TRADE_PLAN_TYPE

    if alert_type == "Early Pump Alert":
        return "early_momentum_continuation"

    if alert_type == "Active Breakout Alert":
        return "active_breakout_continuation"

    if alert_type == "Continuation Alert":
        return "standard_continuation"

    return None


def _with_parabolic_trade_plan(
    result: dict,
    strategy: PaperTradingStrategy,
    reason: str,
) -> dict:
    """Return a result copy with parabolic paper trade metadata attached."""
    trade_plan = {
        **_get_trade_plan(result),
        "trade_plan_type": PARABOLIC_TRADE_PLAN_TYPE,
        "stop_loss_pct": strategy.stop_loss_pct,
        "take_profit_1_pct": strategy.take_profit_1_pct,
        "take_profit_2_pct": strategy.take_profit_2_pct,
        "take_profit_3_pct": strategy.take_profit_3_pct,
        "max_hold_hours": strategy.max_hold_hours,
        "should_paper_trade": True,
        "parabolic_paper_eligible": True,
        "parabolic_paper_reason": reason,
        "reason": reason,
    }

    return {
        **result,
        "trade_plan": trade_plan,
    }


def _get_continuation_target(result: dict) -> str | None:
    """Read the continuation target bucket from a scan result."""
    continuation_target = result.get("continuation_target")

    if isinstance(continuation_target, str):
        return continuation_target

    if not isinstance(continuation_target, dict):
        continuation_target = {}

    return _first_present(continuation_target, "target_bucket", "bucket")


def _get_move_stage(result: dict) -> Any:
    """Read the move stage from nested or flattened alert data."""
    move_stage_signal = result.get("move_stage_signal") or {}

    return _first_present(result, "move_stage") or move_stage_signal.get("stage")


def _get_move_from_recent_low_pct(result: dict) -> Any:
    """Read move-from-low percentage from nested or flattened alert data."""
    move_stage_signal = result.get("move_stage_signal") or {}
    flattened_move_pct = _first_present(result, "move_from_recent_low_pct")

    if flattened_move_pct is not None:
        return flattened_move_pct

    return move_stage_signal.get("move_from_recent_low_pct")


def _get_liquidity_label(result: dict) -> Any:
    """Read the liquidity label from nested or flattened alert data."""
    liquidity_signal = result.get("liquidity_signal") or {}

    return _first_present(result, "liquidity_label") or liquidity_signal.get("label")


def _get_tradability_score(result: dict) -> Any:
    """Read the tradability score from nested or flattened alert data."""
    tradability_signal = result.get("tradability_signal") or {}
    flattened_score = _first_present(result, "tradability_score")

    if flattened_score is not None:
        return flattened_score

    return tradability_signal.get("score")


def _meets_slippage_gate(result: dict, position_size_usd: float) -> tuple[bool, str]:
    """Hard tradability floor: can the real order book absorb this position size?

    Replaces the old coarse PAPER_MIN_LIQUIDITY (24h-volume label) and
    PAPER_MIN_TRADABILITY_SCORE (24h-ticker spread) gates with a direct
    measurement — walk the live Binance order book for the intended position
    size and require the resulting VWAP fill to stay within
    PAPER_SLIPPAGE_BUDGET_PCT of the signal price. This lets volatile-but-
    genuinely-tradeable coins in regardless of their 24h-volume label, while
    still rejecting coins whose book truly can't absorb the size.

    Fails closed (rejects) when the book can't be fetched or lacks enough
    depth to price — we can't confirm tradability, so we don't trade it. A
    transient fetch failure just skips this scan cycle; the symbol is
    re-evaluated next cycle.
    """
    entry_price = _safe_float(result.get("latest_close"), default=None)
    symbol = str(result.get("symbol") or "")

    if entry_price is None or entry_price <= 0:
        return False, "Cannot evaluate slippage: missing or invalid signal price."

    if position_size_usd is None or position_size_usd <= 0:
        return False, "Cannot evaluate slippage: missing or invalid position size."

    quantity = position_size_usd / entry_price
    real_fill_price, _spread_pct = fetch_real_fill(symbol, "buy", quantity)

    if real_fill_price is None:
        return (
            False,
            f"Order book for {symbol} is unavailable or lacks enough depth to "
            f"fill ${position_size_usd:.0f} — cannot confirm tradability.",
        )

    adverse_slippage_pct = max(0.0, (real_fill_price - entry_price) / entry_price * 100)

    if adverse_slippage_pct > PAPER_SLIPPAGE_BUDGET_PCT:
        return (
            False,
            f"Walking the order book for ${position_size_usd:.0f} of {symbol} "
            f"implies {adverse_slippage_pct:.2f}% slippage, over the "
            f"{PAPER_SLIPPAGE_BUDGET_PCT:g}% budget.",
        )

    return (
        True,
        f"Slippage gate passed ({adverse_slippage_pct:.2f}% <= "
        f"{PAPER_SLIPPAGE_BUDGET_PCT:g}%).",
    )


def _meets_hard_trade_gates(result: dict, position_size_usd: float) -> tuple[bool, str]:
    """Non-negotiable gate applied to every alert type before any paper trade opens."""
    return _meets_slippage_gate(result, position_size_usd)


def compute_conviction_position_size(
    result: dict,
    stop_loss_pct: float,
    opportunity_score: float | None,
    risk_config: RiskConfig | None = None,
) -> tuple[float | None, str]:
    """Size a position by conviction, capped by real order-book depth.

    base_size comes from the risk manager's per-trade risk formula
    (portfolio_value × risk_per_trade_pct / |stop_loss_pct|) — previously
    computed but discarded. It's scaled by a 0.5x-1.5x multiplier driven by
    opportunity_score and how much order-book slippage-budget headroom is
    left at that size, then capped at whatever quantity the book can
    actually absorb within PAPER_SLIPPAGE_BUDGET_PCT.

    Returns (position_size_usd, detail). position_size_usd is None — same
    fail-closed rule as the slippage gate — when the book can't be fetched
    or can't absorb any size within budget.
    """
    entry_price = _safe_float(result.get("latest_close"), default=None)
    symbol = str(result.get("symbol") or "")

    if entry_price is None or entry_price <= 0:
        return None, "Cannot size position: missing or invalid signal price."

    base_size = compute_position_size(stop_loss_pct, risk_config)
    base_quantity = base_size / entry_price
    book_eval = evaluate_entry_slippage(
        symbol, base_quantity, entry_price, PAPER_SLIPPAGE_BUDGET_PCT
    )
    adverse_slippage_pct = book_eval["adverse_slippage_pct"]

    if adverse_slippage_pct is None:
        return None, (
            f"Order book for {symbol} is unavailable or lacks enough depth to "
            f"price a ${base_size:.0f} position — cannot confirm tradability."
        )

    tradability_headroom = max(
        0.0,
        min(
            1.0,
            (PAPER_SLIPPAGE_BUDGET_PCT - adverse_slippage_pct) / PAPER_SLIPPAGE_BUDGET_PCT,
        ),
    )
    normalized_score = max(
        0.0, min(1.0, (_safe_float(opportunity_score, default=0.0) or 0.0) / 100)
    )
    conviction = (
        normalized_score * POSITION_SIZE_OPPORTUNITY_WEIGHT
        + tradability_headroom * POSITION_SIZE_TRADABILITY_WEIGHT
    )
    multiplier = POSITION_SIZE_MIN_MULTIPLIER + conviction * (
        POSITION_SIZE_MAX_MULTIPLIER - POSITION_SIZE_MIN_MULTIPLIER
    )
    size_usd = base_size * multiplier

    max_quantity = book_eval["max_quantity_within_budget"] or 0.0
    max_notional = max_quantity * entry_price
    size_usd = min(size_usd, max_notional) if max_notional > 0 else 0.0

    if size_usd <= 0:
        return None, (
            f"Order book for {symbol} cannot absorb any position size within "
            f"the {PAPER_SLIPPAGE_BUDGET_PCT:g}% slippage budget."
        )

    return (
        round(size_usd, 2),
        f"Sized ${size_usd:.2f} at {multiplier:.2f}x conviction "
        f"(score {normalized_score * 100:.0f}, tradability headroom "
        f"{tradability_headroom * 100:.0f}%), capped by book depth.",
    )


def _get_exhaustion_risk_level(result: dict) -> Any:
    """Read exhaustion risk from nested or flattened alert data."""
    exhaustion_signal = result.get("exhaustion_signal") or {}

    return (
        _first_present(result, "exhaustion_risk_level")
        or exhaustion_signal.get("risk_level")
    )


def _get_recent_price_change(result: dict, key: str) -> Any:
    """Read recent price change values from nested or flattened result data."""
    recent_changes = result.get("recent_price_changes") or {}
    flattened_change = _first_present(result, key)

    if flattened_change is not None:
        return flattened_change

    return recent_changes.get(key)


def _get_volume_acceleration_ratio(result: dict, key: str) -> Any:
    """Read volume acceleration ratios from nested or flattened result data."""
    volume_acceleration = result.get("volume_acceleration") or {}
    flattened_ratio = _first_present(result, key)

    if flattened_ratio is not None:
        return flattened_ratio

    return volume_acceleration.get(key)


def _has_parabolic_reacceleration(result: dict) -> bool:
    """Return whether short-term price or volume confirms re-acceleration."""
    volume_acceleration_2h = _safe_float(
        _get_volume_acceleration_ratio(result, "volume_acceleration_2h_ratio")
    )
    change_1h = _safe_float(_get_recent_price_change(result, "change_1h_pct"))
    change_2h = _safe_float(_get_recent_price_change(result, "change_2h_pct"))
    change_4h = _safe_float(_get_recent_price_change(result, "change_4h_pct"))

    return any(
        [
            volume_acceleration_2h >= 2,
            change_1h >= 2,
            change_2h >= 5,
            change_4h >= 10,
        ]
    )


def _first_present(record: dict, *keys: str) -> Any:
    """Return the first non-None value for one of the given keys."""
    for key in keys:
        if record.get(key) is not None:
            return record[key]

    return None


def _safe_float(value: Any, default: float | None = 0.0) -> float | None:
    """Convert a value to float, returning a default on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_json_list(path: str) -> list[dict]:
    """Load a JSON list from disk."""
    json_path = Path(path)

    if not json_path.exists():
        return []

    try:
        with json_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError):
        return []

    if not isinstance(data, list):
        return []

    return [item for item in data if isinstance(item, dict)]


def _save_json_list(path: str, records: list[dict]) -> None:
    """Save a JSON list to disk."""
    json_path = Path(path)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    with json_path.open("w", encoding="utf-8") as file:
        json.dump(records, file, indent=2)


def _utc_now_iso() -> str:
    """Return the current UTC timestamp as ISO text."""
    return datetime.now(timezone.utc).isoformat()
