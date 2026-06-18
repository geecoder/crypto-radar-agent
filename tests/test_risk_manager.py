"""Tests for the portfolio risk manager."""

from datetime import datetime, timedelta, timezone

from app.risk.risk_manager import (
    RiskConfig,
    check_capital_exposure,
    check_correlation,
    check_daily_drawdown,
    check_position_limit,
    compute_position_size,
    evaluate_trade_risk,
)


def _config(**kwargs) -> RiskConfig:
    defaults = dict(
        max_open_positions=5,
        max_capital_deployed_pct=30.0,
        portfolio_value=1000.0,
        risk_per_trade_pct=1.0,
        daily_drawdown_halt_pct=5.0,
        max_correlated_positions=2,
    )
    defaults.update(kwargs)
    return RiskConfig(**defaults)


def _open_trade(symbol: str = "BTCUSDT", size: float = 50.0) -> dict:
    return {"status": "open", "symbol": symbol, "simulated_position_size": size}


def _closed_trade(pnl_amount: float, hours_ago: float = 1.0) -> dict:
    closed_at = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return {
        "status": "closed",
        "pnl_amount": pnl_amount,
        "closed_at": closed_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Gate 1: position limit
# ---------------------------------------------------------------------------

def test_position_limit_allows_when_under_limit() -> None:
    trades = [_open_trade() for _ in range(4)]
    result = check_position_limit(trades, _config(max_open_positions=5))
    assert result.allowed is True


def test_position_limit_blocks_at_limit() -> None:
    trades = [_open_trade() for _ in range(5)]
    result = check_position_limit(trades, _config(max_open_positions=5))
    assert result.allowed is False
    assert "5/5" in result.reason


# ---------------------------------------------------------------------------
# Gate 2: capital exposure
# ---------------------------------------------------------------------------

def test_capital_exposure_allows_when_under_cap() -> None:
    trades = [_open_trade(size=50) for _ in range(2)]  # $100 deployed
    result = check_capital_exposure(trades, _config(portfolio_value=1000, max_capital_deployed_pct=30))
    assert result.allowed is True  # $100 < $300 cap


def test_capital_exposure_blocks_at_cap() -> None:
    trades = [_open_trade(size=100) for _ in range(3)]  # $300 deployed = cap
    result = check_capital_exposure(trades, _config(portfolio_value=1000, max_capital_deployed_pct=30))
    assert result.allowed is False
    assert "cap" in result.reason.lower()


# ---------------------------------------------------------------------------
# Gate 3: position sizing
# ---------------------------------------------------------------------------

def test_compute_position_size_correct() -> None:
    # risk 1% of $1000 on a -10% stop = $10 risk / 0.10 = $100 position
    size = compute_position_size(-10.0, _config(portfolio_value=1000, risk_per_trade_pct=1.0))
    assert size == 100.0


def test_compute_position_size_tighter_stop_means_larger_position() -> None:
    size_tight = compute_position_size(-5.0, _config(portfolio_value=1000, risk_per_trade_pct=1.0))
    size_wide = compute_position_size(-10.0, _config(portfolio_value=1000, risk_per_trade_pct=1.0))
    assert size_tight > size_wide  # tighter stop → larger position for same $risk


# ---------------------------------------------------------------------------
# Gate 4: daily drawdown circuit breaker
# ---------------------------------------------------------------------------

def test_daily_drawdown_allows_when_under_threshold() -> None:
    trades = [_closed_trade(-20.0)]  # $20 loss on $1000 = 2%
    result = check_daily_drawdown(trades, _config(portfolio_value=1000, daily_drawdown_halt_pct=5.0))
    assert result.allowed is True


def test_daily_drawdown_blocks_when_over_threshold() -> None:
    trades = [_closed_trade(-60.0)]  # $60 loss on $1000 = 6%
    result = check_daily_drawdown(trades, _config(portfolio_value=1000, daily_drawdown_halt_pct=5.0))
    assert result.allowed is False
    assert "circuit breaker" in result.reason.lower()


def test_daily_drawdown_ignores_old_trades() -> None:
    trades = [_closed_trade(-200.0, hours_ago=25)]  # outside 24h window
    result = check_daily_drawdown(trades, _config(portfolio_value=1000, daily_drawdown_halt_pct=5.0))
    assert result.allowed is True


def test_daily_drawdown_ignores_profits() -> None:
    trades = [_closed_trade(200.0)]  # profit does not trigger halt
    result = check_daily_drawdown(trades, _config(portfolio_value=1000, daily_drawdown_halt_pct=5.0))
    assert result.allowed is True


# ---------------------------------------------------------------------------
# Gate 5: correlation guard
# ---------------------------------------------------------------------------

def test_correlation_allows_first_meme_coin() -> None:
    result = check_correlation("DOGEUSDT", [], _config(max_correlated_positions=2))
    assert result.allowed is True


def test_correlation_allows_up_to_limit() -> None:
    open_trades = [_open_trade("SHIBUSDT"), _open_trade("PEPEUSDT")]
    result = check_correlation(
        "DOGEUSDT", open_trades, _config(max_correlated_positions=2)
    )
    # 2 already open in the meme group, trying to add a 3rd (DOGE) → blocked
    assert result.allowed is False
    assert "correlation limit" in result.reason.lower()


def test_correlation_allows_uncorrelated_coin() -> None:
    open_trades = [_open_trade("DOGEUSDT"), _open_trade("SHIBUSDT")]
    result = check_correlation(
        "SOLUSDT", open_trades, _config(max_correlated_positions=2)
    )
    # SOL is in a different group
    assert result.allowed is True


# ---------------------------------------------------------------------------
# Composite gate
# ---------------------------------------------------------------------------

def test_evaluate_trade_risk_passes_all_gates() -> None:
    # Use uncorrelated symbols so the correlation gate doesn't fire.
    decision = evaluate_trade_risk(
        symbol="BTCUSDT",
        stop_loss_pct=-10.0,
        open_trades=[_open_trade("AAVEUSDT"), _open_trade("LINKUSDT")],
        closed_trades_today=[_closed_trade(10.0)],
        config=_config(),
    )
    assert decision.allowed is True
    assert decision.position_size_usd == 100.0


def test_evaluate_trade_risk_fails_first_gate_first() -> None:
    # Position limit hit → should short-circuit before other checks.
    open_trades = [_open_trade() for _ in range(5)]
    decision = evaluate_trade_risk(
        symbol="BTCUSDT",
        stop_loss_pct=-10.0,
        open_trades=open_trades,
        closed_trades_today=[],
        config=_config(max_open_positions=5),
    )
    assert decision.allowed is False
    assert "position limit" in decision.reason.lower()
