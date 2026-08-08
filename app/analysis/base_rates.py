"""Historical follow-through base rates by alert type.

The honesty layer for the pivot from autonomous trader to discretionary
decision-support tool (five backtested strategy families found no
autonomous edge after costs — see app/analysis/backtest.py,
exit_model_backtest.py, mean_reversion_backtest.py, liquid_majors_backtest.py
— but the scanner reliably finds real movers, which has genuine value to a
human decision-maker who brings their own judgment).

Computes, from `alert_outcomes` joined with `alert_history`, what fraction
of each alert_type historically reached a given upside threshold — so every
alert shown to a human carries its own real track record ("this alert type
hit +10% 34% of the time") instead of just a raw score. The goal is
explicitly to keep the human honest in real time, not to produce a
recommendation.
"""

DEFAULT_HIT_THRESHOLD_PCT = 10
# Below this many historical alerts of a given type, the hit rate is too
# noisy to lean on — flagged rather than hidden, so the human sees the
# number AND knows not to over-trust it yet.
MIN_SAMPLE_SIZE_FOR_CONFIDENCE = 20


def join_outcomes_with_alert_type(
    alert_history: list[dict],
    alert_outcomes: dict,
) -> list[dict]:
    """Enrich each alert_outcomes record with the alert_type of its
    originating alert_history row (joined on alert_history.id == alert_id).

    alert_outcomes doesn't store alert_type directly — this is the join
    that makes "hit rate BY alert type" possible without a schema change.
    """
    alert_type_by_id = {
        alert.get("id"): alert.get("alert_type")
        for alert in alert_history
        if alert.get("id")
    }

    joined = []

    for alert_id, outcome in alert_outcomes.items():
        alert_type = alert_type_by_id.get(alert_id)

        if not alert_type:
            continue

        joined.append({**outcome, "alert_type": alert_type})

    return joined


def compute_hit_rate_by_alert_type(
    joined_outcomes: list[dict],
    hit_threshold_pct: int = DEFAULT_HIT_THRESHOLD_PCT,
) -> dict[str, dict]:
    """Return {alert_type: {sample_size, hit_count, hit_rate_pct, low_confidence}}
    for every alert_type present in `joined_outcomes`, at one upside threshold.
    """
    hit_key = f"hit_{hit_threshold_pct}pct"
    hits_by_type: dict[str, list[bool]] = {}

    for outcome in joined_outcomes:
        alert_type = outcome.get("alert_type")

        if not alert_type:
            continue

        hits_by_type.setdefault(alert_type, []).append(bool(outcome.get(hit_key)))

    stats = {}

    for alert_type, hits in hits_by_type.items():
        sample_size = len(hits)
        hit_count = sum(hits)
        stats[alert_type] = {
            "sample_size": sample_size,
            "hit_count": hit_count,
            "hit_rate_pct": round(hit_count / sample_size * 100, 1) if sample_size else 0.0,
            "low_confidence": sample_size < MIN_SAMPLE_SIZE_FOR_CONFIDENCE,
        }

    return stats


def format_base_rate_line(
    alert_type: str,
    stats_by_type: dict,
    hit_threshold_pct: int = DEFAULT_HIT_THRESHOLD_PCT,
) -> str:
    """Return a one-line, human-readable base-rate string for one alert
    type, meant to be embedded directly in the alert a human sees.
    """
    stats = stats_by_type.get(alert_type)

    if not stats or stats["sample_size"] == 0:
        return f"No historical track record yet for {alert_type}."

    confidence_note = " — small sample, treat as noisy" if stats["low_confidence"] else ""

    return (
        f"Historically, {alert_type} alerts hit +{hit_threshold_pct}% "
        f"{stats['hit_rate_pct']:.0f}% of the time "
        f"({stats['hit_count']}/{stats['sample_size']} alerts{confidence_note})."
    )
