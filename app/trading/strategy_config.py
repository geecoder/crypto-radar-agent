"""Configurable paper trading strategy presets."""

from dataclasses import dataclass


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


def get_default_paper_trading_strategy() -> PaperTradingStrategy:
    """Return the default momentum-continuation paper trading strategy."""
    return PaperTradingStrategy(
        name="default_momentum_continuation",
        minimum_opportunity_score=65,
        min_move_from_recent_low_pct=3,
        max_move_from_recent_low_pct=20,
        allow_thin_liquidity=False,
        allow_high_exhaustion=False,
        stop_loss_pct=-5,
        take_profit_1_pct=8,
        take_profit_2_pct=15,
        take_profit_3_pct=20,
        max_hold_hours=48,
        simulated_position_size=100,
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
        stop_loss_pct=-7,
        take_profit_1_pct=10,
        take_profit_2_pct=20,
        take_profit_3_pct=35,
        max_hold_hours=48,
        simulated_position_size=100,
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

    return get_default_paper_trading_strategy()
