"""Tests for Binance market priority filtering."""

from app.binance.market_filter import select_priority_symbols, select_scan_universe


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
        "USD1USDT",
        "PAXGUSDT",
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
        {
            "symbol": "USD1USDT",
            "quoteVolume": "900000000",
            "priceChangePercent": "25.0",
            "count": "2000000",
        },
        {
            "symbol": "PAXGUSDT",
            "quoteVolume": "900000000",
            "priceChangePercent": "25.0",
            "count": "2000000",
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


def test_select_scan_universe_includes_priority_top_gainers_and_high_movers() -> None:
    active_symbols = [
        "BTCUSDT",
        "ETHUSDT",
        "EDENUSDT",
        "HOMEUSDT",
        "FASTUSDT",
        "ILLQUSDT",
        "NEGUSDT",
        "USD1USDT",
        "PAXGUSDT",
        "BAD-USDT",
    ]
    tickers_24hr = [
        {
            "symbol": "BTCUSDT",
            "quoteVolume": "600000000",
            "priceChangePercent": "1",
            "count": "1200000",
        },
        {
            "symbol": "ETHUSDT",
            "quoteVolume": "120000000",
            "priceChangePercent": "2",
            "count": "300000",
        },
        {
            "symbol": "EDENUSDT",
            "quoteVolume": "6000000",
            "priceChangePercent": "80",
            "count": "6000",
        },
        {
            "symbol": "HOMEUSDT",
            "quoteVolume": "1000000",
            "priceChangePercent": "12",
            "count": "2000",
        },
        {
            "symbol": "FASTUSDT",
            "quoteVolume": "8000000",
            "priceChangePercent": "6",
            "count": "4000",
        },
        {
            "symbol": "ILLQUSDT",
            "quoteVolume": "1000000",
            "priceChangePercent": "4",
            "count": "1000",
        },
        {
            "symbol": "NEGUSDT",
            "quoteVolume": "10000000",
            "priceChangePercent": "-2",
            "count": "10000",
        },
        {
            "symbol": "USD1USDT",
            "quoteVolume": "900000000",
            "priceChangePercent": "25",
            "count": "2000000",
        },
        {
            "symbol": "PAXGUSDT",
            "quoteVolume": "900000000",
            "priceChangePercent": "25",
            "count": "2000000",
        },
        {
            "symbol": "BAD-USDT",
            "quoteVolume": "900000000",
            "priceChangePercent": "25",
            "count": "2000000",
        },
    ]

    selected = select_scan_universe(
        active_symbols,
        tickers_24hr,
        max_priority_symbols=2,
        max_universe_symbols=10,
    )

    assert selected[:2] == ["BTCUSDT", "ETHUSDT"]
    assert "EDENUSDT" in selected
    assert "HOMEUSDT" in selected
    assert "FASTUSDT" in selected
    assert "NEGUSDT" not in selected
    assert "USD1USDT" not in selected
    assert "PAXGUSDT" not in selected
    assert "BAD-USDT" not in selected
    assert len(selected) == len(set(selected))


def test_select_scan_universe_caps_result_size() -> None:
    active_symbols = [f"COIN{index}USDT" for index in range(20)]
    tickers_24hr = [
        {
            "symbol": symbol,
            "quoteVolume": "6000000",
            "priceChangePercent": str(20 - index),
            "count": "6000",
        }
        for index, symbol in enumerate(active_symbols)
    ]

    selected = select_scan_universe(
        active_symbols,
        tickers_24hr,
        max_priority_symbols=20,
        max_universe_symbols=5,
    )

    assert len(selected) == 5
