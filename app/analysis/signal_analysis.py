"""Signal performance analysis for saved alert outcomes."""

HIT_THRESHOLDS = (5, 10, 20, 50, 100)
SCORE_BANDS = ("0-39", "40-59", "60-69", "70-79", "80-89", "90-100")


def build_signal_analysis(outcomes: dict) -> dict:
    """Analyse completed outcomes by signal condition groups."""
    outcome_records = [
        outcome
        for outcome in outcomes.values()
        if isinstance(outcome, dict)
    ]
    completed_outcomes = [
        outcome
        for outcome in outcome_records
        if is_completed_outcome(outcome)
    ]

    analysis = {
        "total_outcomes": len(outcome_records),
        "completed_outcomes": len(completed_outcomes),
        "pending_outcomes": len(outcome_records) - len(completed_outcomes),
        "by_move_stage": _build_group_metrics(
            completed_outcomes,
            _get_move_stage_group,
        ),
        "by_continuation_target": _build_group_metrics(
            completed_outcomes,
            _get_continuation_target_group,
        ),
        "by_liquidity_label": _build_group_metrics(
            completed_outcomes,
            _get_liquidity_label_group,
        ),
        "by_exhaustion_risk_level": _build_group_metrics(
            completed_outcomes,
            _get_exhaustion_risk_group,
        ),
        "by_score_band": _build_score_band_metrics(completed_outcomes),
    }
    analysis["early_observations"] = _build_early_observations(analysis)
    return analysis


def format_signal_analysis(analysis: dict) -> str:
    """Format signal analysis as a readable plain-text report."""
    lines = [
        "Crypto Radar Signal Analysis",
        "",
        "Overview",
        f"Total outcomes: {analysis.get('total_outcomes', 0)}",
        f"Completed outcomes: {analysis.get('completed_outcomes', 0)}",
        f"Pending outcomes: {analysis.get('pending_outcomes', 0)}",
        "",
        "Performance by Move Stage",
        *_format_group_table(analysis.get("by_move_stage", {})),
        "",
        "Performance by Continuation Target",
        *_format_group_table(analysis.get("by_continuation_target", {})),
        "",
        "Performance by Liquidity",
        *_format_group_table(analysis.get("by_liquidity_label", {})),
        "",
        "Performance by Exhaustion Risk",
        *_format_group_table(analysis.get("by_exhaustion_risk_level", {})),
        "",
        "Performance by Score Band",
        *_format_group_table(analysis.get("by_score_band", {})),
        "",
        "Early Observations",
        *_format_observations(analysis.get("early_observations", [])),
    ]
    return "\n".join(lines)


def is_completed_outcome(outcome: dict) -> bool:
    """Return whether an outcome has at least one completed checkpoint."""
    checkpoints = outcome.get("checkpoints")

    if isinstance(checkpoints, dict):
        if _is_completed_status(checkpoints.get("status")):
            return True

        return any(
            isinstance(checkpoint, dict)
            and _is_completed_status(checkpoint.get("status"))
            for checkpoint in checkpoints.values()
        )

    if isinstance(checkpoints, list):
        return any(
            isinstance(checkpoint, dict)
            and _is_completed_status(checkpoint.get("status"))
            for checkpoint in checkpoints
        )

    return False


def percentage(numerator: int, denominator: int) -> float:
    """Return a percentage rounded to two decimals."""
    if denominator == 0:
        return 0.0

    return round((numerator / denominator) * 100, 2)


def average(values: list[float]) -> float:
    """Return an average rounded to two decimals."""
    clean_values = [
        value
        for value in values
        if value is not None
    ]

    if not clean_values:
        return 0.0

    return round(sum(clean_values) / len(clean_values), 2)


def get_nested_value(data: dict, path: list[str], default=None):
    """Read a nested dictionary value safely."""
    current = data

    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default

        current = current[key]

    if current is None:
        return default

    return current


def _build_group_metrics(outcomes: list[dict], group_getter) -> dict:
    """Build metrics for one grouping strategy."""
    grouped: dict[str, list[dict]] = {}

    for outcome in outcomes:
        group = group_getter(outcome) or "Unknown"
        grouped.setdefault(str(group), []).append(outcome)

    return {
        group: _calculate_group_metrics(group_outcomes)
        for group, group_outcomes in sorted(grouped.items())
    }


def _build_score_band_metrics(outcomes: list[dict]) -> dict:
    """Build metrics for fixed opportunity-score bands."""
    grouped = {band: [] for band in SCORE_BANDS}
    unknown_scores = []

    for outcome in outcomes:
        band = _get_score_band(outcome)

        if band in grouped:
            grouped[band].append(outcome)
        else:
            unknown_scores.append(outcome)

    metrics = {
        band: _calculate_group_metrics(group_outcomes)
        for band, group_outcomes in grouped.items()
    }

    if unknown_scores:
        metrics["Unknown"] = _calculate_group_metrics(unknown_scores)

    return metrics


def _calculate_group_metrics(outcomes: list[dict]) -> dict:
    """Calculate performance metrics for a completed outcome group."""
    count = len(outcomes)
    hit_counts = {
        threshold: _count_hits(outcomes, threshold)
        for threshold in HIT_THRESHOLDS
    }

    return {
        "count": count,
        "average_opportunity_score": average(_numeric_values(outcomes, "opportunity_score")),
        "average_max_upside_pct": average(
            _numeric_values(outcomes, "max_upside_pct", "highest_return_pct")
        ),
        "average_max_drawdown_pct": average(
            _numeric_values(outcomes, "max_drawdown_pct")
        ),
        "hit_5_rate_pct": percentage(hit_counts[5], count),
        "hit_10_rate_pct": percentage(hit_counts[10], count),
        "hit_20_rate_pct": percentage(hit_counts[20], count),
        "hit_50_rate_pct": percentage(hit_counts[50], count),
        "hit_100_rate_pct": percentage(hit_counts[100], count),
    }


def _numeric_values(outcomes: list[dict], *keys: str) -> list[float]:
    """Return numeric values from the first available key in each outcome."""
    values = []

    for outcome in outcomes:
        value = _first_present(outcome, *keys)
        numeric_value = _as_float(value)

        if numeric_value is not None:
            values.append(numeric_value)

    return values


def _count_hits(outcomes: list[dict], threshold: int) -> int:
    """Count outcomes that hit a target threshold."""
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


def _get_move_stage_group(outcome: dict) -> str:
    """Read the move-stage group from common outcome shapes."""
    return _first_nested_value(
        outcome,
        [
            ["move_stage_signal", "stage"],
            ["alert_history", "move_stage_signal", "stage"],
            ["metadata", "move_stage_signal", "stage"],
            ["signal_data", "move_stage_signal", "stage"],
            ["move_stage"],
        ],
        default="Unknown",
    )


def _get_continuation_target_group(outcome: dict) -> str:
    """Read the continuation target group from common outcome shapes."""
    return _first_nested_value(
        outcome,
        [
            ["continuation_target", "target_bucket"],
            ["alert_history", "continuation_target", "target_bucket"],
            ["metadata", "continuation_target", "target_bucket"],
            ["signal_data", "continuation_target", "target_bucket"],
            ["target_bucket"],
        ],
        default="Unknown",
    )


def _get_liquidity_label_group(outcome: dict) -> str:
    """Read the liquidity label group from common outcome shapes."""
    return _first_nested_value(
        outcome,
        [
            ["liquidity_signal", "label"],
            ["alert_history", "liquidity_signal", "label"],
            ["metadata", "liquidity_signal", "label"],
            ["signal_data", "liquidity_signal", "label"],
            ["liquidity_label"],
        ],
        default="Unknown",
    )


def _get_exhaustion_risk_group(outcome: dict) -> str:
    """Read the exhaustion-risk group from common outcome shapes."""
    return _first_nested_value(
        outcome,
        [
            ["exhaustion_signal", "risk_level"],
            ["alert_history", "exhaustion_signal", "risk_level"],
            ["metadata", "exhaustion_signal", "risk_level"],
            ["signal_data", "exhaustion_signal", "risk_level"],
            ["exhaustion_risk_level"],
        ],
        default="Unknown",
    )


def _get_score_band(outcome: dict) -> str:
    """Return the opportunity-score band for one outcome."""
    score = _as_float(outcome.get("opportunity_score"))

    if score is None:
        return "Unknown"

    if score < 40:
        return "0-39"
    if score < 60:
        return "40-59"
    if score < 70:
        return "60-69"
    if score < 80:
        return "70-79"
    if score < 90:
        return "80-89"
    return "90-100"


def _build_early_observations(analysis: dict) -> list[str]:
    """Build early observations from grouped performance metrics."""
    observations = []
    completed_count = analysis.get("completed_outcomes", 0)

    if completed_count < 10:
        observations.append("Sample size is too small for strong conclusions.")

    eligible_groups = _eligible_groups(analysis)

    if not eligible_groups:
        observations.append("More data is needed before comparing signal groups.")
        return observations

    best_group = max(
        eligible_groups,
        key=lambda group: group["metrics"]["average_max_upside_pct"],
    )
    weakest_group = min(
        eligible_groups,
        key=lambda group: group["metrics"]["average_max_drawdown_pct"],
    )
    observations.append(
        "Best upside group so far: "
        f"{best_group['category']} / {best_group['group']} "
        f"({best_group['metrics']['average_max_upside_pct']}% average max upside)."
    )
    observations.append(
        "Weakest drawdown group so far: "
        f"{weakest_group['category']} / {weakest_group['group']} "
        f"({weakest_group['metrics']['average_max_drawdown_pct']}% average max drawdown)."
    )
    return observations


def _eligible_groups(analysis: dict) -> list[dict]:
    """Return groups with enough samples for early observations."""
    group_sections = {
        "Move Stage": analysis.get("by_move_stage", {}),
        "Continuation Target": analysis.get("by_continuation_target", {}),
        "Liquidity": analysis.get("by_liquidity_label", {}),
        "Exhaustion Risk": analysis.get("by_exhaustion_risk_level", {}),
        "Score Band": analysis.get("by_score_band", {}),
    }
    eligible = []

    for category, groups in group_sections.items():
        for group, metrics in groups.items():
            if metrics.get("count", 0) >= 3:
                eligible.append(
                    {
                        "category": category,
                        "group": group,
                        "metrics": metrics,
                    }
                )

    return eligible


def _format_group_table(groups: dict) -> list[str]:
    """Format grouped metrics as compact table rows."""
    if not groups:
        return ["No completed outcomes."]

    lines = [
        "Group | Count | Avg Score | Avg Upside | Avg Drawdown | +5% | +10% | +20% | +50% | +100%",
        "-" * 98,
    ]

    for group, metrics in groups.items():
        lines.append(
            f"{group} | "
            f"{metrics.get('count', 0)} | "
            f"{_format_number(metrics.get('average_opportunity_score', 0))} | "
            f"{_format_number(metrics.get('average_max_upside_pct', 0))}% | "
            f"{_format_number(metrics.get('average_max_drawdown_pct', 0))}% | "
            f"{_format_number(metrics.get('hit_5_rate_pct', 0))}% | "
            f"{_format_number(metrics.get('hit_10_rate_pct', 0))}% | "
            f"{_format_number(metrics.get('hit_20_rate_pct', 0))}% | "
            f"{_format_number(metrics.get('hit_50_rate_pct', 0))}% | "
            f"{_format_number(metrics.get('hit_100_rate_pct', 0))}%"
        )

    return lines


def _format_observations(observations: list[str]) -> list[str]:
    """Format observation lines."""
    if not observations:
        return ["- No observations available yet."]

    return [f"- {observation}" for observation in observations]


def _first_nested_value(data: dict, paths: list[list[str]], default=None):
    """Return the first available nested value from a list of paths."""
    for path in paths:
        value = get_nested_value(data, path, default=None)

        if value not in (None, ""):
            return value

    return default


def _first_present(outcome: dict, *keys: str):
    """Return the first non-None top-level value for one of the given keys."""
    for key in keys:
        if outcome.get(key) is not None:
            return outcome[key]

    return None


def _as_float(value) -> float | None:
    """Convert a value to float when possible."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value) -> bool:
    """Convert common truthy values to bool."""
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}

    return bool(value)


def _is_completed_status(status) -> bool:
    """Return whether a checkpoint status is completed."""
    return str(status).strip().lower() == "completed"


def _format_number(value) -> str:
    """Format numeric values without noisy trailing zeros."""
    numeric_value = _as_float(value) or 0.0
    return f"{numeric_value:.2f}".rstrip("0").rstrip(".")
