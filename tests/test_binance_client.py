"""Tests for Binance public market-data helpers."""

import pandas as pd
import pytest
import requests

from app.binance.client import BinancePublicClient, klines_to_dataframe


@pytest.fixture(autouse=True)
def default_binance_base_url_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep Binance URL order tests independent from the local .env file."""
    monkeypatch.setattr("app.binance.client.BINANCE_BASE_URL_ORDER", "")
    monkeypatch.setattr("app.binance.client.BINANCE_BASE_URL_ORDER_IS_SET", False)


class FakeResponse:
    """Small response stub for no-network client tests."""

    def __init__(self, payload: object, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error

    def raise_for_status(self) -> None:
        if self.error is not None:
            raise self.error

    def json(self) -> object:
        return self.payload


def test_binance_public_client_base_urls_are_ordered() -> None:
    expected_base_urls = [
        "https://data-api.binance.vision",
        "https://api1.binance.com",
        "https://api2.binance.com",
        "https://api3.binance.com",
        "https://api.binance.com",
    ]

    client = BinancePublicClient()

    assert client.base_urls == expected_base_urls


def test_binance_public_client_uses_configured_base_url_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.binance.client.BINANCE_BASE_URL_ORDER",
        "api,api1,api2,api3,data-api",
    )
    monkeypatch.setattr("app.binance.client.BINANCE_BASE_URL_ORDER_IS_SET", True)
    expected_base_urls = [
        "https://api.binance.com",
        "https://api1.binance.com",
        "https://api2.binance.com",
        "https://api3.binance.com",
        "https://data-api.binance.vision",
    ]

    client = BinancePublicClient()

    assert client.base_urls == expected_base_urls


def test_binance_public_client_uses_short_explicit_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.binance.client.BINANCE_BASE_URL_ORDER", "data-api,api")
    monkeypatch.setattr("app.binance.client.BINANCE_BASE_URL_ORDER_IS_SET", True)

    client = BinancePublicClient()

    assert client.base_urls == [
        "https://data-api.binance.vision",
        "https://api.binance.com",
    ]


def test_binance_public_client_falls_back_when_order_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.binance.client.BINANCE_BASE_URL_ORDER", "api,unknown")
    monkeypatch.setattr("app.binance.client.BINANCE_BASE_URL_ORDER_IS_SET", True)

    client = BinancePublicClient()

    assert client.base_urls == [
        "https://data-api.binance.vision",
        "https://api1.binance.com",
        "https://api2.binance.com",
        "https://api3.binance.com",
        "https://api.binance.com",
    ]


def test_binance_public_client_retries_451_with_next_base_url(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    monkeypatch.setattr("app.binance.client.DEBUG", False)

    def fake_get(
        url: str,
        params: dict[str, object] | None = None,
        timeout: int | None = None,
    ) -> FakeResponse:
        calls.append(url)
        if len(calls) == 1:
            return FakeResponse(
                {},
                requests.exceptions.HTTPError("451 Client Error"),
            )
        return FakeResponse({"symbols": []})

    monkeypatch.setattr(requests, "get", fake_get)

    result = BinancePublicClient().get_exchange_info()

    assert result == {"symbols": []}
    assert calls == [
        "https://data-api.binance.vision/api/v3/exchangeInfo",
        "https://api1.binance.com/api/v3/exchangeInfo",
    ]

    output = capsys.readouterr().out
    assert "Binance base URL failed: https://data-api.binance.vision" in output
    assert "451 Client Error" not in output


def test_binance_public_client_prints_error_detail_when_debug_enabled(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    monkeypatch.setattr("app.binance.client.DEBUG", True)

    def fake_get(
        url: str,
        params: dict[str, object] | None = None,
        timeout: int | None = None,
    ) -> FakeResponse:
        calls.append(url)
        if len(calls) == 1:
            return FakeResponse(
                {},
                requests.exceptions.HTTPError("451 Client Error"),
            )
        return FakeResponse({"symbols": []})

    monkeypatch.setattr(requests, "get", fake_get)

    result = BinancePublicClient().get_exchange_info()

    assert result == {"symbols": []}

    output = capsys.readouterr().out
    assert (
        "Binance base URL failed: https://data-api.binance.vision - "
        "451 Client Error"
    ) in output


def test_binance_public_client_raises_runtime_error_after_all_base_urls_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.binance.client.DEBUG", False)

    def fake_get(
        url: str,
        params: dict[str, object] | None = None,
        timeout: int | None = None,
    ) -> FakeResponse:
        return FakeResponse({}, requests.exceptions.Timeout("request timed out"))

    monkeypatch.setattr(requests, "get", fake_get)

    with pytest.raises(RuntimeError) as exc_info:
        BinancePublicClient().get_24hr_tickers()

    message = str(exc_info.value)
    assert "All Binance base URLs failed" in message
    for base_url in BinancePublicClient().base_urls:
        assert base_url in message


def test_binance_public_client_retries_request_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_get(
        url: str,
        params: dict[str, object] | None = None,
        timeout: int | None = None,
    ) -> FakeResponse:
        calls.append(url)
        if len(calls) == 1:
            raise requests.exceptions.RequestException("temporary request failure")
        return FakeResponse([])

    monkeypatch.setattr(requests, "get", fake_get)

    result = BinancePublicClient().get_24hr_tickers()

    assert result == []
    assert calls == [
        "https://data-api.binance.vision/api/v3/ticker/24hr",
        "https://api1.binance.com/api/v3/ticker/24hr",
    ]


def test_binance_market_data_methods_use_shared_get(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object] | None]] = []

    def fake_get(
        self: BinancePublicClient,
        path: str,
        params: dict[str, object] | None = None,
    ) -> object:
        calls.append((path, params))
        return {}

    monkeypatch.setattr(BinancePublicClient, "_get", fake_get)

    client = BinancePublicClient()
    client.get_exchange_info()
    client.get_24hr_tickers()
    client.get_24hr_ticker("BTCUSDT")
    client.get_klines("btcusdt", interval="1h", limit=50)

    assert calls == [
        ("/api/v3/exchangeInfo", None),
        ("/api/v3/ticker/24hr", None),
        ("/api/v3/ticker/24hr", {"symbol": "BTCUSDT"}),
        (
            "/api/v3/klines",
            {"symbol": "btcusdt", "interval": "1h", "limit": 50},
        ),
    ]


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


def test_get_klines_includes_time_range_when_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object] | None]] = []

    def fake_get(
        self: BinancePublicClient,
        path: str,
        params: dict[str, object] | None = None,
    ) -> object:
        calls.append((path, params))
        return []

    monkeypatch.setattr(BinancePublicClient, "_get", fake_get)

    client = BinancePublicClient()
    client.get_klines("BTCUSDT", interval="15m", limit=200, start_time_ms=1000, end_time_ms=2000)

    assert calls == [
        (
            "/api/v3/klines",
            {
                "symbol": "BTCUSDT",
                "interval": "15m",
                "limit": 200,
                "startTime": 1000,
                "endTime": 2000,
            },
        ),
    ]


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
