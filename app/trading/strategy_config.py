"""Configurable paper trading strategy presets."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PaperTradingStrategy:
    """Entry and exit settings for simulated paper trades."""

    name: str
    minimum_opportunity_score: int
    min_move_from_recent_low_pct: float
    max_move_from_recent_low_pct: float
    allow_thin_liquidity: bool
    allow_high_exhaustion: bool
    stop_loss_pct: float
    take_profit_1_pct: float
    take_profit_2_pct: float
    take_profit_3_pct: float
    max_hold_hours: int
    simulated_position_size: float
    # Extended hold for high-scoring trades (score >= high_score_threshold).
    high_score_threshold: int = 60
    high_score_max_hold_hours: int = 48
    # Trailing stop: move stop to breakeven once up breakeven_trigger_pct,
    # then trail at trail_pct below the running peak once up activate_trigger_pct.
    trailing_stop_breakeven_pct: float = 10.0
    trailing_stop_activate_pct: float = 25.0
    trailing_stop_trail_pct: float = 15.0
    # Partial take-profits: fractions of position closed at TP1 and TP2;
    # the remainder rides until TP3, trailing stop, or max-hold expiry.
    partial_tp1_fraction: float = 0.5
    partial_tp2_fraction: float = 0.3


def get_default_paper_trading_strategy() -> PaperTradingStrategy:
    """Return the default momentum-continuation paper trading strategy."""
    return PaperTradingStrategy(
        name="default_momentum_continuation",
        minimum_opportunity_score=55,
        min_move_from_recent_low_pct=3,
        max_move_from_recent_low_pct=20,
        allow_thin_liquidity=True,
        allow_high_exhaustion=False,
        # Widened from -5% to -10% — crypto routinely wicks through -7%.
        # Position halved from 100 → 50 so dollar-risk-per-trade stays constant.
        stop_loss_pct=-10,
        take_profit_1_pct=8,
        take_profit_2_pct=15,
        take_profit_3_pct=20,
        max_hold_hours=24,
        high_score_max_hold_hours=48,
        simulated_position_size=50,
    )


def get_conservative_paper_trading_strategy() -> PaperTradingStrategy:
    """Return a tighter paper trading strategy for higher-confidence setups."""
    return PaperTradingStrategy(
        name="conservative_momentum",
        minimum_opportunity_score=75,
        min_move_from_recent_low_pct=3,
        max_move_from_recent_low_pct=15,
        allow_thin_liquidity=False,
        allow_high_exhaustion=False,
        stop_loss_pct=-3,
        take_profit_1_pct=6,
        take_profit_2_pct=10,
        take_profit_3_pct=15,
        max_hold_hours=24,
        simulated_position_size=100,
    )


def get_aggressive_paper_trading_strategy() -> PaperTradingStrategy:
    """Return a wider high-volatility paper trading strategy."""
    return PaperTradingStrategy(
        name="aggressive_high_volatility",
        minimum_opportunity_score=65,
        min_move_from_recent_low_pct=5,
        max_move_from_recent_low_pct=30,
        allow_thin_liquidity=False,
        allow_high_exhaustion=False,
        stop_loss_pct=-10,
        take_profit_1_pct=10,
        take_profit_2_pct=20,
        take_profit_3_pct=35,
        max_hold_hours=48,
        simulated_position_size=70,
    )


def get_parabolic_paper_strategy() -> PaperTradingStrategy:
    """Return the high-risk parabolic continuation paper-only strategy."""
    return PaperTradingStrategy(
        name="parabolic_continuation_paper",
        minimum_opportunity_score=25,
        min_move_from_recent_low_pct=50,
        max_move_from_recent_low_pct=150,
        allow_thin_liquidity=True,
        allow_high_exhaustion=False,
        stop_loss_pct=-8,
        take_profit_1_pct=12,
        take_profit_2_pct=25,
        take_profit_3_pct=50,
        max_hold_hours=24,
        simulated_position_size=25,
    )


def get_speculative_early_runner_strategy() -> PaperTradingStrategy:
    """Return the high-risk speculative early-runner paper-only strategy."""
    return PaperTradingStrategy(
        name="speculative_early_runner_paper",
        minimum_opportunity_score=40,
        min_move_from_recent_low_pct=5,
        max_move_from_recent_low_pct=20,
        allow_thin_liquidity=True,
        allow_high_exhaustion=False,
        stop_loss_pct=-10,
        take_profit_1_pct=10,
        take_profit_2_pct=20,
        take_profit_3_pct=35,
        max_hold_hours=24,
        simulated_position_size=25,
    )


def get_tradability_experiment_strategy() -> PaperTradingStrategy:
    """Return the tradability-score experiment paper-only strategy.

    Trades Thin/Very-thin liquidity coins that the PAPER_MIN_LIQUIDITY floor
    would otherwise block, purely to observe whether tradability_score
    predicts NET profitability independent of the coarse liquidity label.
    Small position size and paper-only — excluded from go-live gate math.
    """
    return PaperTradingStrategy(
        name="tradability_experiment_paper",
        minimum_opportunity_score=55,
        min_move_from_recent_low_pct=3,
        max_move_from_recent_low_pct=20,
        allow_thin_liquidity=True,
        allow_high_exhaustion=False,
        stop_loss_pct=-10,
        take_profit_1_pct=8,
        take_profit_2_pct=15,
        take_profit_3_pct=20,
        max_hold_hours=24,
        simulated_position_size=10,
    )


def get_strategy_by_name(name: str | None) -> PaperTradingStrategy:
    """Return a paper trading strategy by short CLI name."""
    if name is None:
        return get_default_paper_trading_strategy()

    normalized_name = name.strip().lower()

    if normalized_name in {"", "default"}:
        return get_default_paper_trading_strategy()

    if normalized_name == "conservative":
        return get_conservative_paper_trading_strategy()

    if normalized_name == "aggressive":
        return get_aggressive_paper_trading_strategy()

    if normalized_name == "parabolic":
        return get_parabolic_paper_strategy()

    if normalized_name in {"speculative", "early-runner", "early_runner"}:
        return get_speculative_early_runner_strategy()

    return get_default_paper_trading_strategy()
