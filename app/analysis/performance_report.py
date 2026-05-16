"""Performance summary reporting for saved alert outcomes."""

HIT_THRESHOLDS = (5, 10, 20, 50, 100)


def build_performance_report(outcomes: dict) -> dict:
    """Build a summary report from saved outcome records."""
    outcome_records = [
        outcome
        for outcome in outcomes.values()
        if isinstance(outcome, dict)
    ]
    completed = [
        outcome
        for outcome in outcome_records
        if _has_completed_checkpoint(outcome)
    ]
    completed_count = len(completed)
    hit_counts = {
        threshold: _count_hits(completed, threshold)
        for threshold in HIT_THRESHOLDS
    }

    return {
        "total_outcomes": len(outcome_records),
        "completed_outcomes": completed_count,
        "pending_outcomes": len(outcome_records) - completed_count,
        "hit_5_count": hit_counts[5],
        "hit_10_count": hit_counts[10],
        "hit_20_count": hit_counts[20],
        "hit_50_count": hit_counts[50],
        "hit_100_count": hit_counts[100],
        "hit_5_rate_pct": _rate(hit_counts[5], completed_count),
        "hit_10_rate_pct": _rate(hit_counts[10], completed_count),
        "hit_20_rate_pct": _rate(hit_counts[20], completed_count),
        "hit_50_rate_pct": _rate(hit_counts[50], completed_count),
        "hit_100_rate_pct": _rate(hit_counts[100], completed_count),
        "average_max_upside_pct": _average_metric(
            completed,
            "max_upside_pct",
            "highest_return_pct",
        ),
        "average_max_drawdown_pct": _average_metric(
            completed,
            "max_drawdown_pct",
        ),
        "best_symbol_by_max_upside": _best_by_metric(
            completed,
            "max_upside_pct",
            "highest_return_pct",
        ),
        "worst_symbol_by_drawdown": _worst_by_metric(
            completed,
            "max_drawdown_pct",
        ),
        "top_5_symbols_by_max_upside": _top_by_metric(
            completed,
            "max_upside_pct",
            "highest_return_pct",
            limit=5,
        ),
        "top_5_symbols_by_opportunity_score": _top_by_metric(
            completed,
            "opportunity_score",
            limit=5,
        ),
        "average_opportunity_score": _average_metric(
            completed,
            "opportunity_score",
        ),
        "average_upside_by_classification": _average_by_group(
            completed,
            "classification",
            "max_upside_pct",
            "highest_return_pct",
        ),
        "average_upside_by_target_bucket": _average_by_group(
            completed,
            "target_bucket",
            "max_upside_pct",
            "highest_return_pct",
        ),
    }


def format_performance_report(report: dict) -> str:
    """Format a performance report as readable plain text."""
    lines = [
        "Crypto Radar Performance Report",
        "",
        "Overview",
        f"Total outcomes: {report.get('total_outcomes', 0)}",
        f"Completed outcomes: {report.get('completed_outcomes', 0)}",
        f"Pending outcomes: {report.get('pending_outcomes', 0)}",
        f"Average opportunity score: {_format_pct(report.get('average_opportunity_score', 0))}",
        "",
        "Hit Rates",
        _format_hit_line(report, 5),
        _format_hit_line(report, 10),
        _format_hit_line(report, 20),
        _format_hit_line(report, 50),
        _format_hit_line(report, 100),
        "",
        "Upside and Drawdown",
        f"Average max upside: {_format_pct(report.get('average_max_upside_pct', 0))}%",
        f"Average max drawdown: {_format_pct(report.get('average_max_drawdown_pct', 0))}%",
        "",
        "Best/Worst Symbols",
        f"Best by max upside: {_format_symbol_metric(report.get('best_symbol_by_max_upside'), 'max_upside_pct')}",
        f"Worst by drawdown: {_format_symbol_metric(report.get('worst_symbol_by_drawdown'), 'max_drawdown_pct')}",
        "Top 5 by max upside:",
        *_format_symbol_list(report.get("top_5_symbols_by_max_upside", []), "max_upside_pct"),
        "Top 5 by opportunity score:",
        *_format_symbol_list(
            report.get("top_5_symbols_by_opportunity_score", []),
            "opportunity_score",
        ),
        "",
        "By Classification",
        *_format_group_average(report.get("average_upside_by_classification", {})),
        "",
        "By Target Bucket",
        *_format_group_average(report.get("average_upside_by_target_bucket", {})),
        "",
        "Notes",
        *_build_notes(report),
    ]

    return "\n".join(lines)


def _has_completed_checkpoint(outcome: dict) -> bool:
    """Return whether any checkpoint has status completed."""
    checkpoints = outcome.get("checkpoints")

    if isinstance(checkpoints, dict):
        if _status_is_completed(checkpoints.get("status")):
            return True

        return any(
            isinstance(checkpoint, dict)
            and _status_is_completed(checkpoint.get("status"))
            for checkpoint in checkpoints.values()
        )

    if isinstance(checkpoints, list):
        return any(
            isinstance(checkpoint, dict)
            and _status_is_completed(checkpoint.get("status"))
            for checkpoint in checkpoints
        )

    return False


def _status_is_completed(status: object) -> bool:
    """Return whether a checkpoint status means completed."""
    return str(status).lower() == "completed"


def _count_hits(outcomes: list[dict], threshold: int) -> int:
    """Count completed outcomes that hit a target threshold."""
    return sum(
        1
        for outcome in outcomes
        if _as_bool(
            _first_present(
                outcome,
                f"hit_{threshold}_pct",
                f"hit_{threshold}pct",
            )
        )
    )


def _rate(count: int, total: int) -> float:
    """Return a percentage rate rounded to two decimals."""
    if total == 0:
        return 0.0

    return round((count / total) * 100, 2)


def _average_metric(outcomes: list[dict], *keys: str) -> float:
    """Average the first available numeric metric from each outcome."""
    values = [
        value
        for outcome in outcomes
        if (value := _as_float(_first_present(outcome, *keys))) is not None
    ]

    if not values:
        return 0.0

    return round(sum(values) / len(values), 2)


def _average_by_group(outcomes: list[dict], group_key: str, *metric_keys: str) -> dict:
    """Average a numeric metric for each group value."""
    grouped_values: dict[str, list[float]] = {}

    for outcome in outcomes:
        group = outcome.get(group_key) or "Unknown"
        value = _as_float(_first_present(outcome, *metric_keys))

        if value is None:
            continue

        grouped_values.setdefault(str(group), []).append(value)

    return {
        group: round(sum(values) / len(values), 2)
        for group, values in sorted(grouped_values.items())
    }


def _best_by_metric(outcomes: list[dict], *keys: str) -> dict | None:
    """Return the symbol record with the highest metric value."""
    ranked = _rank_by_metric(outcomes, *keys, reverse=True)

    if not ranked:
        return None

    return ranked[0]


def _worst_by_metric(outcomes: list[dict], *keys: str) -> dict | None:
    """Return the symbol record with the lowest metric value."""
    ranked = _rank_by_metric(outcomes, *keys, reverse=False)

    if not ranked:
        return None

    return ranked[0]


def _top_by_metric(
    outcomes: list[dict],
    *keys: str,
    limit: int,
) -> list[dict]:
    """Return the top symbols for a metric."""
    return _rank_by_metric(outcomes, *keys, reverse=True)[:limit]


def _rank_by_metric(outcomes: list[dict], *keys: str, reverse: bool) -> list[dict]:
    """Rank outcomes by one numeric metric."""
    ranked = []

    for outcome in outcomes:
        value = _as_float(_first_present(outcome, *keys))

        if value is None:
            continue

        ranked.append(
            {
                "symbol": outcome.get("symbol") or "Unknown",
                "alert_id": outcome.get("alert_id"),
                "value": round(value, 2),
                "metric": keys[0],
            }
        )

    return sorted(ranked, key=lambda item: item["value"], reverse=reverse)


def _first_present(outcome: dict, *keys: str) -> object:
    """Return the first non-None value for the given keys."""
    for key in keys:
        if outcome.get(key) is not None:
            return outcome[key]

    return None


def _as_float(value: object) -> float | None:
    """Convert a value to float when possible."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: object) -> bool:
    """Convert common truthy values to bool."""
    if isinstance(value, str):
        return value.lower() in {"true", "1", "yes"}

    return bool(value)


def _format_hit_line(report: dict, threshold: int) -> str:
    """Format one hit-rate line."""
    return (
        f"Hit +{threshold}%: "
        f"{report.get(f'hit_{threshold}_count', 0)} "
        f"({_format_pct(report.get(f'hit_{threshold}_rate_pct', 0))}%)"
    )


def _format_pct(value: object) -> str:
    """Format a numeric value without noisy trailing zeros."""
    number = _as_float(value) or 0.0
    formatted = f"{number:.2f}".rstrip("0").rstrip(".")
    return formatted


def _format_symbol_metric(record: dict | None, metric_key: str) -> str:
    """Format a single symbol metric."""
    if not record:
        return "Not available"

    suffix = "" if metric_key == "opportunity_score" else "%"
    return f"{record['symbol']} ({_format_pct(record['value'])}{suffix})"


def _format_symbol_list(records: list[dict], metric_key: str) -> list[str]:
    """Format a ranked symbol list."""
    if not records:
        return ["- Not available"]

    suffix = "" if metric_key == "opportunity_score" else "%"
    return [
        f"- {record['symbol']}: {_format_pct(record['value'])}{suffix}"
        for record in records
    ]


def _format_group_average(group_averages: dict) -> list[str]:
    """Format grouped average upside values."""
    if not group_averages:
        return ["- Not available"]

    return [
        f"- {group}: {_format_pct(average)}%"
        for group, average in group_averages.items()
    ]


def _build_notes(report: dict) -> list[str]:
    """Build plain-English caveats for the report."""
    notes = []

    if report.get("total_outcomes", 0) == 0:
        notes.append(
            "No outcome data available yet. Let the bot run until alerts are "
            "generated and checked."
        )

    if report.get("completed_outcomes", 0) < 10:
        notes.append("Sample size is still small. Avoid drawing strong conclusions yet.")

    if report.get("hit_20_rate_pct", 0) == 0:
        notes.append("No +20% moves have been confirmed yet.")

    if not notes:
        notes.append("Review performance over time as more outcomes complete.")

    return [f"- {note}" for note in notes]
