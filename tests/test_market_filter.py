"""Tests for Binance market priority filtering."""

from app.binance.market_filter import select_priority_symbols


def test_select_priority_symbols_filters_and_ranks_by_priority_score() -> None:
    active_symbols = [
        "BTCUSDT",
        "ETHUSDT",
        "DOGEUSDT",
        "LOWUSDT",
        "QUIETUSDT",
        "BADUSDT",
        "BTCEUR",
        "BAD-USDT",
        "badUSDT",
    ]
    tickers_24hr = [
        {
            "symbol": "BTCUSDT",
            "quoteVolume": "600000000",
            "priceChangePercent": "1.5",
            "count": "1200000",
        },
        {
            "symbol": "ETHUSDT",
            "quoteVolume": "120000000",
            "priceChangePercent": "-12.0",
            "count": "300000",
        },
        {
            "symbol": "DOGEUSDT",
            "quoteVolume": "60000000",
            "priceChangePercent": "22.0",
            "count": "60000",
        },
        {
            "symbol": "SOLUSDT",
            "quoteVolume": "900000000",
            "priceChangePercent": "25.0",
            "count": "2000000",
        },
        {
            "symbol": "LOWUSDT",
            "quoteVolume": "4999999",
            "priceChangePercent": "50.0",
            "count": "100000",
        },
        {
            "symbol": "QUIETUSDT",
            "quoteVolume": "20000000",
            "priceChangePercent": "8.0",
            "count": "4999",
        },
        {
            "symbol": "BADUSDT",
            "quoteVolume": "not-a-number",
            "priceChangePercent": "not-a-number",
            "count": "not-a-number",
        },
        {
            "symbol": "BTCEUR",
            "quoteVolume": "600000000",
            "priceChangePercent": "10.0",
            "count": "1200000",
        },
        {
            "symbol": "BAD-USDT",
            "quoteVolume": "600000000",
            "priceChangePercent": "10.0",
            "count": "1200000",
        },
        {
            "symbol": "badUSDT",
            "quoteVolume": "600000000",
            "priceChangePercent": "10.0",
            "count": "1200000",
        },
    ]

    selected = select_priority_symbols(active_symbols, tickers_24hr, max_symbols=2)

    assert selected == ["ETHUSDT", "BTCUSDT"]


def test_select_priority_symbols_allows_boundary_values() -> None:
    selected = select_priority_symbols(
        active_symbols=["MINUSDT"],
        tickers_24hr=[
            {
                "symbol": "MINUSDT",
                "quoteVolume": "5000000",
                "priceChangePercent": "0",
                "count": "5000",
            }
        ],
    )

    assert selected == ["MINUSDT"]
