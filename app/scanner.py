"""Multi-symbol scanning helpers for the Crypto Radar Agent."""

import time

from app.binance.client import klines_to_dataframe
from app.indicators.breakout import calculate_breakout_strength
from app.indicators.continuation import calculate_continuation_target
from app.indicators.exhaustion import calculate_exhaustion_risk
from app.indicators.liquidity import calculate_liquidity_quality
from app.indicators.momentum import calculate_price_momentum
from app.indicators.move_stage import calculate_move_stage
from app.indicators.trend import calculate_trend_alignment
from app.indicators.volatility import calculate_volatility_potential
from app.indicators.volume import calculate_volume_spike
from app.scoring.opportunity_score import calculate_opportunity_score

SCAN_DELAY_SECONDS = 0.1


def _get_opportunity_score(result: dict) -> int:
    """Read an opportunity score safely from a scan result."""
    try:
        return int(result.get("opportunity", {}).get("opportunity_score", 0))
    except (TypeError, ValueError):
        return 0


def _get_valid_results(results: list[dict]) -> list[dict]:
    """Return scan results that do not contain errors."""
    return [result for result in results if "error" not in result]


def scan_symbol(
    client,
    symbol: str,
    interval: str = "15m",
    limit: int = 100,
    ticker_24hr: dict | None = None,
) -> dict:
    """Scan one symbol and return indicator plus opportunity-score data."""
    try:
        klines = client.get_klines(symbol, interval=interval, limit=limit)
        candles = klines_to_dataframe(klines)

        if candles.empty:
            raise ValueError(f"No candle data returned for {symbol}")

        latest_close = float(candles["close"].iloc[-1])
        volume_signal = calculate_volume_spike(candles)
        momentum_signal = calculate_price_momentum(candles)
        breakout_signal = calculate_breakout_strength(candles)
        trend_signal = calculate_trend_alignment(candles)
        volatility_signal = calculate_volatility_potential(candles)
        move_stage_signal = calculate_move_stage(candles)
        exhaustion_signal = calculate_exhaustion_risk(candles)
        liquidity_signal = calculate_liquidity_quality(ticker_24hr or {})
        opportunity = calculate_opportunity_score(
            volume_signal,
            momentum_signal,
            breakout_signal,
            trend_signal,
            volatility_signal,
            move_stage_signal,
            liquidity_signal,
            exhaustion_signal,
        )
        continuation_target = calculate_continuation_target(
            opportunity["opportunity_score"],
            move_stage_signal,
            volume_signal,
            momentum_signal,
            breakout_signal,
            trend_signal,
            volatility_signal,
            liquidity_signal,
            exhaustion_signal,
        )

        return {
            "symbol": symbol,
            "latest_close": latest_close,
            "volume_signal": volume_signal,
            "momentum_signal": momentum_signal,
            "breakout_signal": breakout_signal,
            "trend_signal": trend_signal,
            "volatility_signal": volatility_signal,
            "move_stage_signal": move_stage_signal,
            "exhaustion_signal": exhaustion_signal,
            "liquidity_signal": liquidity_signal,
            "opportunity": opportunity,
            "continuation_target": continuation_target,
        }
    except Exception as error:
        return {
            "symbol": symbol,
            "error": str(error),
        }


def scan_symbols(
    client,
    symbols: list[str],
    interval: str = "15m",
    limit: int = 100,
    max_symbols: int = 30,
    tickers_24hr: list[dict] | None = None,
) -> list[dict]:
    """Scan symbols and return successful results ranked by opportunity score."""
    symbols_to_scan = symbols[:max_symbols]
    ticker_by_symbol = _build_ticker_by_symbol(client, tickers_24hr)
    results = []

    for index, symbol in enumerate(symbols_to_scan):
        result = scan_symbol(
            client,
            symbol,
            interval=interval,
            limit=limit,
            ticker_24hr=ticker_by_symbol.get(symbol),
        )

        if "error" not in result:
            results.append(result)

        if index < len(symbols_to_scan) - 1:
            time.sleep(SCAN_DELAY_SECONDS)

    return sorted(
        results,
        key=_get_opportunity_score,
        reverse=True,
    )


def _build_ticker_by_symbol(client, tickers_24hr: list[dict] | None = None) -> dict:
    """Return Binance 24-hour ticker data keyed by symbol."""
    if tickers_24hr is None and hasattr(client, "get_24hr_tickers"):
        tickers_24hr = client.get_24hr_tickers()

    if not tickers_24hr:
        return {}

    return {
        ticker.get("symbol"): ticker
        for ticker in tickers_24hr
        if ticker.get("symbol")
    }


def get_alert_candidates(
    results: list[dict],
    minimum_score: int = 60,
) -> list[dict]:
    """Return valid scan results that meet the alert score threshold."""
    candidates = [
        result
        for result in _get_valid_results(results)
        if _get_opportunity_score(result) >= minimum_score
    ]

    return sorted(candidates, key=_get_opportunity_score, reverse=True)


def get_best_setups(results: list[dict], limit: int = 10) -> list[dict]:
    """Return the highest-scoring valid scan results."""
    valid_results = _get_valid_results(results)
    sorted_results = sorted(valid_results, key=_get_opportunity_score, reverse=True)

    return sorted_results[:limit]
