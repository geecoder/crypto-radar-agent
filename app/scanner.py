"""Multi-symbol scanning helpers for the Crypto Radar Agent."""

import time

from app.binance.client import klines_to_dataframe
from app.indicators.breakout import calculate_breakout_strength
from app.indicators.momentum import calculate_price_momentum
from app.indicators.volume import calculate_volume_spike
from app.scoring.opportunity_score import calculate_opportunity_score

SCAN_DELAY_SECONDS = 0.1


def scan_symbol(
    client,
    symbol: str,
    interval: str = "15m",
    limit: int = 100,
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
        opportunity = calculate_opportunity_score(
            volume_signal,
            momentum_signal,
            breakout_signal,
        )

        return {
            "symbol": symbol,
            "latest_close": latest_close,
            "volume_signal": volume_signal,
            "momentum_signal": momentum_signal,
            "breakout_signal": breakout_signal,
            "opportunity": opportunity,
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
) -> list[dict]:
    """Scan symbols and return successful results ranked by opportunity score."""
    symbols_to_scan = symbols[:max_symbols]
    results = []

    for index, symbol in enumerate(symbols_to_scan):
        result = scan_symbol(client, symbol, interval=interval, limit=limit)

        if "error" not in result:
            results.append(result)

        if index < len(symbols_to_scan) - 1:
            time.sleep(SCAN_DELAY_SECONDS)

    return sorted(
        results,
        key=lambda result: result["opportunity"]["opportunity_score"],
        reverse=True,
    )
