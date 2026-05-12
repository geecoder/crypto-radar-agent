"""Tests for text reporting helpers."""

from app.reporting import format_opportunity_table, format_top_opportunity_detail


def _sample_result() -> dict:
    return {
        "symbol": "BTCUSDT",
        "latest_close": 100.5,
        "volume_signal": {"score": 80, "reason": "Volume is elevated."},
        "momentum_signal": {"score": 60, "reason": "Momentum is improving."},
        "breakout_signal": {"score": 40, "reason": "Breakout is early."},
        "trend_signal": {"score": 100, "reason": "Trend is aligned."},
        "volatility_signal": {"score": 20, "reason": "Volatility is modest."},
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
    assert "Volume signal: score 80 - Volume is elevated." in detail
    assert "Momentum signal: score 60 - Momentum is improving." in detail
    assert "Breakout signal: score 40 - Breakout is early." in detail
    assert "Trend signal: score 100 - Trend is aligned." in detail
    assert "Volatility signal: score 20 - Volatility is modest." in detail
    assert "This is an alert candidate." in detail


def test_format_top_opportunity_detail_shows_not_available_for_missing_signal() -> None:
    result = _sample_result()
    result.pop("trend_signal")
    result["opportunity"]["opportunity_score"] = 35

    detail = format_top_opportunity_detail(result)

    assert "Trend signal: Not available" in detail
    assert "This setup is weak. The signals are not sufficiently aligned." in detail
