"""Tests for Binance symbol filtering helpers."""

from app.binance.symbols import get_active_usdt_symbols


def test_get_active_usdt_symbols_filters_to_regular_trading_spot_symbols() -> None:
    exchange_info = {
        "symbols": [
            {
                "symbol": "ETHUSDT",
                "baseAsset": "ETH",
                "quoteAsset": "USDT",
                "status": "TRADING",
                "isSpotTradingAllowed": True,
            },
            {
                "symbol": "BTCUSDT",
                "baseAsset": "BTC",
                "quoteAsset": "USDT",
                "status": "TRADING",
                "isSpotTradingAllowed": True,
            },
            {
                "symbol": "BTCUSDC",
                "baseAsset": "BTC",
                "quoteAsset": "USDC",
                "status": "TRADING",
                "isSpotTradingAllowed": True,
            },
            {
                "symbol": "ADAUSDT",
                "baseAsset": "ADA",
                "quoteAsset": "USDT",
                "status": "BREAK",
                "isSpotTradingAllowed": True,
            },
            {
                "symbol": "BNBUSDT",
                "baseAsset": "BNB",
                "quoteAsset": "USDT",
                "status": "TRADING",
                "isSpotTradingAllowed": False,
            },
            {
                "symbol": "BTCUPUSDT",
                "baseAsset": "BTCUP",
                "quoteAsset": "USDT",
                "status": "TRADING",
                "isSpotTradingAllowed": True,
            },
            {
                "symbol": "USDCUSDT",
                "baseAsset": "USDC",
                "quoteAsset": "USDT",
                "status": "TRADING",
                "isSpotTradingAllowed": True,
            },
        ]
    }

    assert get_active_usdt_symbols(exchange_info) == ["BTCUSDT", "ETHUSDT"]


def test_get_active_usdt_symbols_allows_missing_spot_flag() -> None:
    exchange_info = {
        "symbols": [
            {
                "symbol": "SOLUSDT",
                "baseAsset": "SOL",
                "quoteAsset": "USDT",
                "status": "TRADING",
            }
        ]
    }

    assert get_active_usdt_symbols(exchange_info) == ["SOLUSDT"]
