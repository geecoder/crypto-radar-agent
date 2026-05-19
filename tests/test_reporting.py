"""Tests for text reporting helpers."""

from app.reporting import (
    format_alert_message,
    format_opportunity_table,
    format_top_opportunity_detail,
)


def _sample_result() -> dict:
    return {
        "symbol": "BTCUSDT",
        "latest_close": 100.5,
        "volume_signal": {"score": 80, "reason": "Volume is elevated."},
        "momentum_signal": {"score": 60, "reason": "Momentum is improving."},
        "breakout_signal": {"score": 40, "reason": "Breakout is early."},
        "trend_signal": {"score": 100, "reason": "Trend is aligned."},
        "volatility_signal": {"score": 20, "reason": "Volatility is modest."},
        "move_stage_signal": {
            "score": 90,
            "stage": "Stage 3 - Confirmed early momentum",
            "move_from_recent_low_pct": 8.5,
            "reason": "Price is 8.50% above the recent low.",
        },
        "exhaustion_signal": {
            "risk_score": 20,
            "risk_level": "Low",
            "reason": "Low exhaustion risk.",
        },
        "liquidity_signal": {
            "score": 80,
            "label": "Strong",
            "reason": "Strong liquidity.",
        },
        "continuation_target": {
            "target_bucket": "+50% high-volatility watch",
            "confidence": "Medium",
            "reason": "Strong continuation profile.",
        },
        "opportunity": {
            "opportunity_score": 72,
            "classification": "Watchlist",
            "target_bucket": "+20% momentum setup",
            "risk_level": "Medium",
            "summary": "Watchlist. Some signals are improving.",
        },
    }


def test_format_opportunity_table_returns_readable_table() -> None:
    table = format_opportunity_table([_sample_result()])

    assert "Symbol | Score | Classification | Target Bucket | Risk | Latest Close" in table
    assert "BTCUSDT | 72 | Watchlist | +20% momentum setup | Medium | 100.5" in table


def test_format_opportunity_table_handles_empty_results() -> None:
    table = format_opportunity_table([])

    assert "Symbol | Score | Classification | Target Bucket | Risk | Latest Close" in table
    assert "No results." in table


def test_format_top_opportunity_detail_includes_all_signal_reasons() -> None:
    detail = format_top_opportunity_detail(_sample_result())

    assert "Symbol: BTCUSDT" in detail
    assert "Latest close: 100.5" in detail
    assert "Opportunity score: 72" in detail
    assert "Classification: Watchlist" in detail
    assert "Target bucket: +20% momentum setup" in detail
    assert "Risk level: Medium" in detail
    assert "Summary: Watchlist. Some signals are improving." in detail
    assert "Move Stage: Stage 3 - Confirmed early momentum" in detail
    assert "Move From Recent Low %: 8.50%" in detail
    assert "Continuation Target: +50% high-volatility watch" in detail
    assert "Exhaustion Risk: Low" in detail
    assert "Liquidity Quality: Strong" in detail
    assert "Volume signal: score 80 - Volume is elevated." in detail
    assert "Momentum signal: score 60 - Momentum is improving." in detail
    assert "Breakout signal: score 40 - Breakout is early." in detail
    assert "Trend signal: score 100 - Trend is aligned." in detail
    assert "Volatility signal: score 20 - Volatility is modest." in detail
    assert "Move stage signal: score 90 - Price is 8.50% above the recent low." in detail
    assert "Liquidity signal: score 80 - Strong liquidity." in detail
    assert "Exhaustion risk: Low (score 20) - Low exhaustion risk." in detail
    assert "This is an alert candidate." in detail


def test_format_top_opportunity_detail_shows_not_available_for_missing_signal() -> None:
    result = _sample_result()
    result.pop("trend_signal")
    result["opportunity"]["opportunity_score"] = 35

    detail = format_top_opportunity_detail(result)

    assert "Trend signal: Not available" in detail
    assert "This setup is weak. The signals are not sufficiently aligned." in detail


def test_format_alert_message_returns_telegram_html() -> None:
    message = format_alert_message([_sample_result()])

    assert "<b>🚨 Crypto Radar Alert Candidates</b>" in message
    assert "<b>BTCUSDT</b>" in message
    assert "Alert Type: Continuation Alert" in message
    assert "Opportunity score: 72" in message
    assert "Classification: Watchlist" in message
    assert "Target bucket: +20% momentum setup" in message
    assert "Risk level: Medium" in message
    assert "Move Stage: Stage 3 - Confirmed early momentum" in message
    assert "Move From Recent Low %: 8.50%" in message
    assert "Continuation Target: +50% high-volatility watch" in message
    assert "Confidence: Medium" in message
    assert "Exhaustion Risk: Low" in message
    assert "Liquidity Quality: Strong" in message
    assert "Latest close: 100.5" in message
    assert "Summary: Watchlist. Some signals are improving." in message
    assert "Not financial advice. Use this as a monitoring signal only." in message


def test_format_alert_message_includes_explosive_mover_context() -> None:
    result = _sample_result()
    result["alert_type"] = "Parabolic Watch Alert"
    result["recent_price_changes"] = {
        "change_15m_pct": 10,
        "change_30m_pct": 20,
        "change_1h_pct": 30,
        "change_2h_pct": 40,
        "change_4h_pct": 55,
        "change_24h_pct": 80,
    }
    result["volume_acceleration"] = {
        "volume_acceleration_1h_ratio": 5,
        "volume_acceleration_2h_ratio": 3,
    }
    result["explosive_mover"] = {
        "alert_type": "Parabolic Watch Alert",
        "should_alert": True,
        "potential_bucket": "High-risk parabolic watch",
        "confidence": "High",
        "reason": (
            "This is not a clean entry signal. It is a high-risk market "
            "activity alert."
        ),
    }

    message = format_alert_message([result])

    assert "Alert Type: Parabolic Watch Alert" in message
    assert "Opportunity score: 72" in message
    assert "15m change: 10.00%" in message
    assert "24h change: 80.00%" in message
    assert "Volume acceleration 1h: 5.00x" in message
    assert "Potential bucket: High-risk parabolic watch" in message
    assert "Confidence: High" in message
    assert (
        "High risk. This is a market activity alert, not a clean entry signal. "
        "Avoid chasing vertical candles. Watch for pullback/retest."
    ) in message


def test_format_alert_message_escapes_html_values() -> None:
    result = _sample_result()
    result["symbol"] = "BAD<USDT"
    result["opportunity"]["summary"] = "Price < resistance & volume > average"

    message = format_alert_message([result])

    assert "BAD&lt;USDT" in message
    assert "Price &lt; resistance &amp; volume &gt; average" in message
