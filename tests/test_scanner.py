"""Tests for multi-symbol scanning helpers."""

from app.scanner import (
    get_alert_candidates,
    get_best_setups,
    scan_symbol,
    scan_symbols,
)


class FakeClient:
    """Small fake Binance client for scanner tests."""

    def get_klines(self, symbol: str, interval: str = "15m", limit: int = 100) -> list:
        rows = []

        for index in range(20):
            rows.append(
                [
                    index,
                    "100",
                    "100",
                    "95",
                    "100",
                    "10",
                    index + 1,
                ]
            )

        rows.append(
            [
                20,
                "100",
                "116",
                "99",
                "116",
                "50",
                21,
            ]
        )

        return rows


class FailingClient:
    """Fake client that raises an error for scanner tests."""

    def get_klines(self, symbol: str, interval: str = "15m", limit: int = 100) -> list:
        raise RuntimeError("request failed")


def test_scan_symbol_returns_signals_and_opportunity_score() -> None:
    result = scan_symbol(FakeClient(), "BTCUSDT")

    assert result["symbol"] == "BTCUSDT"
    assert result["latest_close"] == 116.0
    assert result["volume_signal"]["score"] == 100
    assert result["momentum_signal"]["score"] == 100
    assert result["breakout_signal"]["score"] == 100
    assert result["trend_signal"]["score"] == 100
    assert result["volatility_signal"]["score"] == 80
    assert result["opportunity"]["opportunity_score"] == 97


def test_scan_symbol_returns_error_when_symbol_fails() -> None:
    result = scan_symbol(FailingClient(), "BADUSDT")

    assert result["symbol"] == "BADUSDT"
    assert result["error"] == "request failed"


def test_scan_symbols_limits_skips_errors_and_sorts_results(monkeypatch) -> None:
    def fake_scan_symbol(client, symbol: str, interval: str = "15m", limit: int = 100):
        results = {
            "AAAUSDT": {
                "symbol": "AAAUSDT",
                "latest_close": 1.0,
                "opportunity": {"opportunity_score": 20},
            },
            "BBBUSDT": {
                "symbol": "BBBUSDT",
                "latest_close": 2.0,
                "opportunity": {"opportunity_score": 80},
            },
            "CCCUSDT": {"symbol": "CCCUSDT", "error": "failed"},
        }
        return results[symbol]

    monkeypatch.setattr("app.scanner.scan_symbol", fake_scan_symbol)
    monkeypatch.setattr("app.scanner.time.sleep", lambda seconds: None)

    results = scan_symbols(
        client=object(),
        symbols=["AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT"],
        max_symbols=3,
    )

    assert [result["symbol"] for result in results] == ["BBBUSDT", "AAAUSDT"]


def test_get_alert_candidates_filters_errors_and_minimum_score() -> None:
    results = [
        {
            "symbol": "AAAUSDT",
            "opportunity": {"opportunity_score": 60},
        },
        {
            "symbol": "BBBUSDT",
            "opportunity": {"opportunity_score": 85},
        },
        {
            "symbol": "CCCUSDT",
            "opportunity": {"opportunity_score": 59},
        },
        {
            "symbol": "BADUSDT",
            "error": "failed",
        },
    ]

    candidates = get_alert_candidates(results, minimum_score=60)

    assert [result["symbol"] for result in candidates] == ["BBBUSDT", "AAAUSDT"]


def test_get_best_setups_filters_errors_sorts_and_limits_results() -> None:
    results = [
        {
            "symbol": "AAAUSDT",
            "opportunity": {"opportunity_score": 20},
        },
        {
            "symbol": "BBBUSDT",
            "opportunity": {"opportunity_score": 80},
        },
        {
            "symbol": "CCCUSDT",
            "opportunity": {"opportunity_score": 40},
        },
        {
            "symbol": "BADUSDT",
            "error": "failed",
        },
    ]

    best_setups = get_best_setups(results, limit=2)

    assert [result["symbol"] for result in best_setups] == ["BBBUSDT", "CCCUSDT"]
