"""Tests for speculative runner paper-trading risk controls."""

from app.trading import paper_trading
from app.trading.paper_trading import (
    can_create_more_trades_for_alert_type,
    create_paper_trades_from_alerts,
)
from app.trading.trade_plan import generate_trade_plan


def _speculative_runner_result(**overrides) -> dict:
    result = {
        "id": "alert-runner",
        "symbol": "RUNNERUSDT",
        "latest_close": 0.02,
        "alert_type": "Speculative Early Runner Alert",
        "opportunity": {
            "opportunity_score": 55,
            "classification": "High-risk watch",
            "target_bucket": "High-risk early runner watch",
        },
        "move_stage_signal": {
            "stage": "Stage 2 - Early move",
            "move_from_recent_low_pct": 8,
        },
        "recent_price_changes": {
            "change_1h_pct": 2.5,
            "change_2h_pct": 4.5,
            "change_4h_pct": 6.5,
        },
        "volume_acceleration": {
            "volume_acceleration_1h_ratio": 2.1,
            "volume_acceleration_2h_ratio": 1.1,
        },
        "liquidity_signal": {"label": "Thin"},
        "exhaustion_signal": {"risk_level": "Medium"},
    }

    for key, value in overrides.items():
        if key in {"opportunity", "move_stage_signal", "recent_price_changes", "volume_acceleration", "liquidity_signal", "exhaustion_signal"}:
            result[key] = {**result[key], **value}
        else:
            result[key] = value

    result["trade_plan"] = generate_trade_plan(result)
    return result


def _paper_allowed(result: dict) -> tuple[bool, str]:
    trade_plan = result["trade_plan"]
    return bool(trade_plan["should_paper_trade"]), trade_plan["reason"]


def test_speculative_runner_rejected_when_score_below_40() -> None:
    allowed, reason = _paper_allowed(
        _speculative_runner_result(opportunity={"opportunity_score": 39})
    )

    assert allowed is False
    assert reason == "Rejected speculative runner: opportunity score below 40."


def test_speculative_runner_rejected_when_target_bucket_has_no_upside() -> None:
    # "No clear upside setup" is rejected only when score < 50 and no low-signal override.
    # Default fixture has score=55, so we must drop it below 50 to trigger rejection.
    allowed, reason = _paper_allowed(
        _speculative_runner_result(opportunity={"opportunity_score": 45, "target_bucket": "No clear upside setup"})
    )

    assert allowed is False
    assert "no clear upside setup" in reason.lower()


def test_speculative_runner_allowed_when_classification_is_ignore() -> None:
    # Classification is no longer a blocking criterion for speculative runners.
    allowed, reason = _paper_allowed(
        _speculative_runner_result(opportunity={"classification": "Ignore"})
    )

    assert allowed is True


def test_speculative_runner_allowed_when_liquidity_is_very_thin() -> None:
    # Very thin liquidity is explicitly allowed for speculative paper-only simulation.
    allowed, reason = _paper_allowed(
        _speculative_runner_result(liquidity_signal={"label": "Very thin"})
    )

    assert allowed is True


def test_speculative_runner_rejected_when_volume_acceleration_below_2x() -> None:
    allowed, reason = _paper_allowed(
        _speculative_runner_result(
            volume_acceleration={
                "volume_acceleration_1h_ratio": 1.9,
                "volume_acceleration_2h_ratio": 1.8,
            }
        )
    )

    assert allowed is False
    assert reason == "Rejected speculative runner: volume acceleration below 2x."


def test_speculative_runner_accepted_when_all_tightened_rules_pass() -> None:
    allowed, reason = _paper_allowed(_speculative_runner_result())

    assert allowed is True
    assert reason == "Speculative early runner paper trade eligible."


def test_open_alert_type_concentration_limit_blocks_new_speculative_trade(
    monkeypatch,
) -> None:
    candidate = _speculative_runner_result()
    open_trades = [
        {
            "id": f"paper-open-{index}",
            "symbol": f"OPEN{index}USDT",
            "status": "open",
            "alert_type": "Speculative Early Runner Alert",
        }
        for index in range(5)
    ]
    inserted_decisions = []
    updated_alerts = []

    monkeypatch.setattr(paper_trading, "USE_SUPABASE", True)
    monkeypatch.setattr(paper_trading, "_get_open_paper_trades", lambda: open_trades)
    monkeypatch.setattr(
        paper_trading.supabase_store,
        "insert_paper_trade_decision",
        inserted_decisions.append,
    )
    monkeypatch.setattr(
        paper_trading.supabase_store,
        "update_alert_paper_trade_status",
        lambda alert_id, created, paper_trade_id, skip_reason: updated_alerts.append(
            (alert_id, created, paper_trade_id, skip_reason)
        ),
    )

    allowed, reason = can_create_more_trades_for_alert_type(
        "Speculative Early Runner Alert",
        open_trades,
    )
    decisions = create_paper_trades_from_alerts([candidate])

    assert allowed is False
    assert reason == "Open trade limit reached for Speculative Early Runner Alert."
    assert decisions[0]["decision"] == "skipped"
    assert decisions[0]["eligible"] is False
    assert decisions[0]["reason"] == reason
    assert inserted_decisions[0]["reason"] == reason
    assert updated_alerts[0][3] == reason
