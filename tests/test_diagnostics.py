"""Tests for missed mover diagnostic helpers."""

from types import SimpleNamespace

from app.diagnostics import (
    diagnose_symbol,
    format_diagnostic_report,
    get_recommendation,
    get_rejection_reasons,
)


def _diagnostic_result(score: int = 55) -> dict:
    return {
        "symbol": "ENJUSDT",
        "latest_close": 0.1234,
        "volume_signal": {"score": 20},
        "momentum_signal": {"score": 60},
        "breakout_signal": {"score": 0},
        "trend_signal": {"score": 80},
        "volatility_signal": {"score": 40},
        "move_stage_signal": {
            "score": 45,
            "stage": "Stage 5 - Extended move",
            "move_from_recent_low_pct": 25.5,
        },
        "liquidity_signal": {"score": 40, "label": "Thin"},
        "exhaustion_signal": {"risk_score": 60, "risk_level": "High"},
        "continuation_target": {
            "target_bucket": "No clear continuation setup",
            "confidence": "Low",
        },
        "opportunity": {
            "opportunity_score": score,
            "classification": "Weak signal",
            "target_bucket": "No clear upside setup",
            "component_scores": {
                "volume": 20,
                "momentum": 60,
                "breakout": 0,
                "trend": 80,
                "volatility": 40,
                "move_stage": 45,
                "liquidity": 40,
                "exhaustion_risk": 60,
            },
        },
    }


def test_diagnose_symbol_fetches_symbol_ticker_and_scans_normalized_symbol(
    monkeypatch,
) -> None:
    captured = {}
    fake_client = SimpleNamespace(
        get_24hr_ticker=lambda symbol: {
            "symbol": symbol,
            "quoteVolume": "5000000",
            "count": "5000",
        },
    )

    def fake_scan_symbol(client, symbol, interval="15m", limit=100, ticker_24hr=None):
        captured["client"] = client
        captured["symbol"] = symbol
        captured["interval"] = interval
        captured["limit"] = limit
        captured["ticker_24hr"] = ticker_24hr
        return _diagnostic_result()

    monkeypatch.setattr("app.diagnostics.scan_symbol", fake_scan_symbol)

    result = diagnose_symbol(fake_client, " enjusdt ", alert_threshold=60)

    assert result["symbol"] == "ENJUSDT"
    assert result["diagnostic"]["alert_threshold"] == 60
    assert result["diagnostic"]["would_alert"] is False
    assert captured["client"] is fake_client
    assert captured["symbol"] == "ENJUSDT"
    assert captured["interval"] == "15m"
    assert captured["limit"] == 100
    assert captured["ticker_24hr"]["symbol"] == "ENJUSDT"


def test_get_rejection_reasons_returns_all_diagnostic_flags() -> None:
    reasons = get_rejection_reasons(_diagnostic_result(), alert_threshold=60)

    assert reasons == [
        "Rejected: score below alert threshold.",
        "Rejected/penalised: liquidity is thin.",
        "Rejected/penalised: exhaustion risk is high.",
        "Rejected/penalised: no valid continuation target.",
        "Weak confirmation: volume expansion is insufficient.",
        "Weak confirmation: no breakout confirmed.",
        "Late move risk: price may already be extended.",
    ]


def test_get_rejection_reasons_handles_score_below_threshold() -> None:
    result = _diagnostic_result(score=59)
    result["liquidity_signal"]["label"] = "Good"
    result["exhaustion_signal"]["risk_level"] = "Low"
    result["continuation_target"]["target_bucket"] = "+20% continuation watch"
    result["volume_signal"]["score"] = 40
    result["breakout_signal"]["score"] = 40
    result["move_stage_signal"]["move_from_recent_low_pct"] = 5

    reasons = get_rejection_reasons(result, alert_threshold=60)

    assert reasons == ["Rejected: score below alert threshold."]


def test_get_rejection_reasons_handles_thin_liquidity() -> None:
    result = _diagnostic_result(score=70)
    result["exhaustion_signal"]["risk_level"] = "Low"
    result["continuation_target"]["target_bucket"] = "+20% continuation watch"
    result["volume_signal"]["score"] = 40
    result["breakout_signal"]["score"] = 40
    result["move_stage_signal"]["move_from_recent_low_pct"] = 5

    reasons = get_rejection_reasons(result, alert_threshold=60)

    assert reasons == ["Rejected/penalised: liquidity is thin."]


def test_get_rejection_reasons_handles_high_exhaustion_risk() -> None:
    result = _diagnostic_result(score=70)
    result["liquidity_signal"]["label"] = "Good"
    result["continuation_target"]["target_bucket"] = "+20% continuation watch"
    result["volume_signal"]["score"] = 40
    result["breakout_signal"]["score"] = 40
    result["move_stage_signal"]["move_from_recent_low_pct"] = 5

    reasons = get_rejection_reasons(result, alert_threshold=60)

    assert reasons == ["Rejected/penalised: exhaustion risk is high."]


def test_get_recommendation_qualifies_near_miss_and_clear_reject() -> None:
    assert (
        get_recommendation(_diagnostic_result(score=60), alert_threshold=60)
        == "This symbol currently qualifies as an alert candidate."
    )
    assert (
        get_recommendation(_diagnostic_result(score=50), alert_threshold=60)
        == "Near miss. Monitor if volume/breakout improves."
    )
    assert (
        get_recommendation(_diagnostic_result(score=49), alert_threshold=60)
        == "Does not currently qualify."
    )


def test_format_diagnostic_report_includes_required_fields_and_reasons() -> None:
    report = format_diagnostic_report(_diagnostic_result(), alert_threshold=60)

    assert "Missed Mover Diagnostic" in report
    assert "Symbol: ENJUSDT" in report
    assert "Latest close: 0.1234" in report
    assert "Opportunity score: 55" in report
    assert "Alert threshold: 60" in report
    assert "Would alert? No" in report
    assert "Classification: Weak signal" in report
    assert "Target bucket: No clear upside setup" in report
    assert "Continuation target: No clear continuation setup" in report
    assert "Move stage: Stage 5 - Extended move" in report
    assert "Move from recent low %: 25.50%" in report
    assert "Liquidity label: Thin" in report
    assert "Exhaustion risk: High" in report
    assert "- volume: 20" in report
    assert "- exhaustion_risk: 60" in report
    assert "Rejected: score below alert threshold." in report
    assert "Near miss. Monitor if volume/breakout improves." in report


def test_format_diagnostic_report_handles_scan_errors() -> None:
    report = format_diagnostic_report(
        {"symbol": "BADUSDT", "error": "request failed"},
        alert_threshold=60,
    )

    assert "Missed Mover Diagnostic" in report
    assert "Symbol: BADUSDT" in report
    assert "Market data unavailable. Diagnosis skipped." in report
    assert "Error: request failed" in report


def test_diagnose_symbol_handles_unavailable_market_data_gracefully(capsys) -> None:
    def fail_ticker(symbol: str):
        print("Binance retry noise")
        raise RuntimeError("Binance request failed")

    fake_client = SimpleNamespace(
        get_24hr_ticker=fail_ticker,
    )

    result = diagnose_symbol(fake_client, "badusdt", alert_threshold=60)

    assert result["symbol"] == "BADUSDT"
    assert result["error"] == "Binance request failed"
    assert result["diagnostic"] == {
        "alert_threshold": 60,
        "would_alert": False,
    }
    assert "Binance retry noise" not in capsys.readouterr().out
