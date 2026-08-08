"""Tests for the ranked opportunity feed (composite scoring + formatting)."""

from app.analysis import opportunity_feed as feed


def _stub_liquidity(spread_pct, adverse_slippage_pct, headroom_score):
    return lambda symbol, entry_price, position_size_usd=200.0: {
        "spread_pct": spread_pct,
        "adverse_slippage_pct": adverse_slippage_pct,
        "headroom_score": headroom_score,
    }


def _candidate(symbol="BICOUSDT", alert_type="Active Breakout Alert", opportunity_score=62, tradability_score=70, liquidity_label="Good", latest_close=1.5):
    return {
        "symbol": symbol,
        "alert_type": alert_type,
        "opportunity": {"opportunity_score": opportunity_score},
        "tradability_signal": {"score": tradability_score},
        "liquidity_signal": {"label": liquidity_label},
        "latest_close": latest_close,
    }


def test_compute_composite_score_blends_all_four_inputs() -> None:
    base_rates = {"Active Breakout Alert": {"sample_size": 34, "hit_count": 12, "hit_rate_pct": 35.3, "low_confidence": False}}
    stub = _stub_liquidity(spread_pct=0.02, adverse_slippage_pct=0.1, headroom_score=93.3)

    scored = feed.compute_composite_score(_candidate(), base_rates, live_liquidity_check=stub)

    assert scored["symbol"] == "BICOUSDT"
    assert scored["alert_type"] == "Active Breakout Alert"
    assert scored["opportunity_score"] == 62.0
    assert scored["tradability_score"] == 70.0
    assert scored["liquidity_label"] == "Good"
    assert scored["spread_pct"] == 0.02
    assert scored["base_rate_stats"]["hit_rate_pct"] == 35.3

    expected = 62 * 0.35 + 70 * 0.15 + 93.3 * 0.25 + 35.3 * 0.25
    assert scored["composite_score"] == round(expected, 1)


def test_compute_composite_score_handles_missing_base_rate() -> None:
    stub = _stub_liquidity(spread_pct=0.05, adverse_slippage_pct=0.2, headroom_score=86.7)

    scored = feed.compute_composite_score(_candidate(alert_type="Brand New Alert Type"), {}, live_liquidity_check=stub)

    assert scored["base_rate_stats"] == {}
    # Missing base rate contributes 0, not an error.
    expected = 62 * 0.35 + 70 * 0.15 + 86.7 * 0.25 + 0 * 0.25
    assert scored["composite_score"] == round(expected, 1)


def test_compute_composite_score_skips_liquidity_check_without_entry_price() -> None:
    calls = []

    def tracking_stub(symbol, entry_price, position_size_usd=200.0):
        calls.append(symbol)
        return {"spread_pct": 0.01, "adverse_slippage_pct": 0.01, "headroom_score": 99.0}

    candidate = _candidate(latest_close=None)
    scored = feed.compute_composite_score(candidate, {}, live_liquidity_check=tracking_stub)

    assert calls == []
    assert scored["spread_pct"] is None


def test_rank_opportunities_sorts_best_composite_first() -> None:
    stub_strong = _stub_liquidity(spread_pct=0.01, adverse_slippage_pct=0.05, headroom_score=96.7)
    stub_weak = _stub_liquidity(spread_pct=0.5, adverse_slippage_pct=1.4, headroom_score=6.7)

    strong_candidate = _candidate(symbol="STRONGUSDT", opportunity_score=90, tradability_score=90)
    weak_candidate = _candidate(symbol="WEAKUSDT", opportunity_score=40, tradability_score=30)

    # Use the same live_liquidity_check for both by symbol-dispatching inside one stub.
    def dispatch(symbol, entry_price, position_size_usd=200.0):
        return stub_strong(symbol, entry_price) if symbol == "STRONGUSDT" else stub_weak(symbol, entry_price)

    ranked = feed.rank_opportunities(
        [weak_candidate, strong_candidate], {}, live_liquidity_check=dispatch
    )

    assert [item["symbol"] for item in ranked] == ["STRONGUSDT", "WEAKUSDT"]


def test_rank_opportunities_respects_top_n() -> None:
    candidates = [_candidate(symbol=f"SYM{i}USDT") for i in range(5)]
    stub = _stub_liquidity(0.02, 0.1, 90.0)

    ranked = feed.rank_opportunities(candidates, {}, live_liquidity_check=stub, top_n=2)

    assert len(ranked) == 2


def test_format_opportunity_feed_shows_decision_inputs_not_a_decision() -> None:
    base_rates = {"Active Breakout Alert": {"sample_size": 34, "hit_count": 12, "hit_rate_pct": 34.0, "low_confidence": False}}
    stub = _stub_liquidity(spread_pct=0.02, adverse_slippage_pct=0.1, headroom_score=93.3)
    ranked = feed.rank_opportunities([_candidate()], base_rates, live_liquidity_check=stub)

    message = feed.format_opportunity_feed(ranked)

    assert "BICOUSDT" in message
    assert "Active Breakout Alert" in message
    assert "Good liquidity" in message
    assert "spread 0.020%" in message
    assert "hit +10% 34% of the time" in message
    assert "Decision inputs, not a decision" in message
    assert "not financial advice" in message.lower()


def test_format_opportunity_feed_handles_empty_list() -> None:
    message = feed.format_opportunity_feed([])

    assert "No live setups" in message
