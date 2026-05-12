"""Tests for Binance public market-data helpers."""

import pandas as pd

from app.binance.client import klines_to_dataframe


def test_klines_to_dataframe_keeps_candle_columns_and_converts_types() -> None:
    klines = [
        [
            1704067200000,
            "42000.50",
            "42100.00",
            "41900.25",
            "42050.75",
            "123.456",
            1704068099999,
            "0",
            0,
            "0",
            "0",
            "0",
        ]
    ]

    candles = klines_to_dataframe(klines)

    assert list(candles.columns) == [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
    ]
    assert candles.loc[0, "open"] == 42000.50
    assert candles.loc[0, "high"] == 42100.00
    assert candles.loc[0, "low"] == 41900.25
    assert candles.loc[0, "close"] == 42050.75
    assert candles.loc[0, "volume"] == 123.456
    assert candles.loc[0, "open_time"] == pd.Timestamp("2024-01-01 00:00:00")
    assert candles.loc[0, "close_time"] == pd.Timestamp("2024-01-01 00:14:59.999")


def test_klines_to_dataframe_handles_empty_klines() -> None:
    candles = klines_to_dataframe([])

    assert candles.empty
    assert list(candles.columns) == [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
    ]
