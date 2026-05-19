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
        "recent_price_changes": {
            "change_15m_pct": 1,
            "change_30m_pct": 2,
            "change_1h_pct": 3,
            "change_2h_pct": 4,
            "change_4h_pct": 5,
            "change_24h_pct": 6,
        },
        "volume_acceleration": {
            "volume_acceleration_1h_ratio": 1.5,
            "volume_acceleration_2h_ratio": 2,
            "score": 60,
        },
        "explosive_mover": {
            "alert_type": "No explosive mover alert",
            "should_alert": False,
            "reason": "Explosive mover conditions are not strong enough.",
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
        "trade_plan": {
            "trade_plan_type": "no_trade_plan",
            "recommended_action": "Monitor only",
            "entry_approach": "No alert-specific trade plan is available.",
            "invalidation_rule": "No alert trigger is active.",
            "risk_note": "No clean trade plan generated.",
            "should_paper_trade": False,
            "reason": "No supported alert type is active.",
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
    assert "Explosive mover alert type: No explosive mover alert" in report
    assert "Explosive mover should_alert: false" in report
    assert "Explosive mover conditions are not strong enough." in report
    assert "Would trigger Continuation Alert? false" in report
    assert "Would trigger Early Pump Alert? false" in report
    assert "Would trigger Active Breakout Alert? false" in report
    assert "Would trigger Parabolic Watch Alert? false" in report
    assert "Move stage: Stage 5 - Extended move" in report
    assert "Move from recent low %: 25.50%" in report
    assert "Liquidity label: Thin" in report
    assert "Exhaustion risk: High" in report
    assert "- 15m: 1.00%" in report
    assert "- 24h: 6.00%" in report
    assert "- 1h ratio: 1.50x" in report
    assert "- 2h ratio: 2.00x" in report
    assert "Trade Plan:" in report
    assert "- Type: no_trade_plan" in report
    assert "- Recommended action: Monitor only" in report
    assert "- Should paper trade: false" in report
    assert "- volume: 20" in report
    assert "- exhaustion_risk: 60" in report
    assert "Rejected: score below alert threshold." in report
    assert "Near miss. Monitor if volume/breakout improves." in report


def test_format_diagnostic_report_marks_explosive_mover_as_alert_candidate() -> None:
    result = _diagnostic_result(score=35)
    result["explosive_mover"] = {
        "alert_type": "Parabolic Watch Alert",
        "should_alert": True,
        "reason": (
            "This is not a clean entry signal. It is a high-risk market "
            "activity alert."
        ),
    }
    result["trade_plan"] = {
        "trade_plan_type": "parabolic_watch_only",
        "recommended_action": "Watch only; do not chase",
        "entry_approach": (
            "Wait for pullback, consolidation, or retest. "
            "No clean entry currently."
        ),
        "invalidation_rule": "No clean trade plan generated.",
        "risk_note": (
            "Very high risk. This is a market activity alert, not a clean "
            "entry signal."
        ),
        "should_paper_trade": False,
        "reason": "Parabolic watch alerts are monitoring-only.",
    }

    report = format_diagnostic_report(result, alert_threshold=60)

    assert "Would alert? Yes" in report
    assert "Explosive mover alert type: Parabolic Watch Alert" in report
    assert "Explosive mover should_alert: true" in report
    assert "Would trigger Parabolic Watch Alert? true" in report
    assert "- Type: parabolic_watch_only" in report
    assert "- No clean trade plan generated." in report
    assert "- Monitoring only." in report
    assert "- Paper trade skipped." in report
    assert (
        "This qualifies as a Parabolic Watch Alert but not as a clean trade setup."
    ) in report


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
