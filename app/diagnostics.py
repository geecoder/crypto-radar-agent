"""Diagnostic reporting for missed mover analysis."""

from contextlib import redirect_stdout
from io import StringIO

from app.scanner import scan_symbol

NO_VALID_CONTINUATION_TARGETS = {
    "No clear continuation setup",
    "Avoid / late chase",
}


def diagnose_symbol(
    client,
    symbol: str,
    alert_threshold: int = 60,
    interval: str = "15m",
    limit: int = 100,
) -> dict:
    """Fetch market data for one symbol and calculate scanner diagnostics."""
    normalized_symbol = symbol.strip().upper()
    try:
        with redirect_stdout(StringIO()):
            ticker_24hr = _fetch_symbol_ticker_24hr(client, normalized_symbol)
            result = scan_symbol(
                client,
                normalized_symbol,
                interval=interval,
                limit=limit,
                ticker_24hr=ticker_24hr,
            )
    except Exception as error:
        result = {
            "symbol": normalized_symbol,
            "error": str(error),
        }

    result["diagnostic"] = {
        "alert_threshold": alert_threshold,
        "would_alert": _get_opportunity_score(result) >= alert_threshold,
    }
    return result


def format_diagnostic_report(result: dict, alert_threshold: int = 60) -> str:
    """Build a plain-text diagnostic report for one scan result."""
    if "error" in result:
        return "\n".join(
            [
                "Missed Mover Diagnostic",
                f"Symbol: {result.get('symbol', 'Not available')}",
                "Market data unavailable. Diagnosis skipped.",
                f"Error: {result.get('error', 'Not available')}",
            ]
        )

    opportunity = result.get("opportunity", {})
    move_stage = result.get("move_stage_signal", {})
    liquidity = result.get("liquidity_signal", {})
    exhaustion = result.get("exhaustion_signal", {})
    continuation = result.get("continuation_target", {})
    component_scores = opportunity.get("component_scores", {})
    score = _get_opportunity_score(result)
    would_alert = score >= alert_threshold

    lines = [
        "Missed Mover Diagnostic",
        f"Symbol: {result.get('symbol', 'Not available')}",
        f"Latest close: {result.get('latest_close', 'Not available')}",
        f"Opportunity score: {opportunity.get('opportunity_score', 'Not available')}",
        f"Alert threshold: {alert_threshold}",
        f"Would alert? {'Yes' if would_alert else 'No'}",
        f"Classification: {opportunity.get('classification', 'Not available')}",
        f"Target bucket: {opportunity.get('target_bucket', 'Not available')}",
        (
            "Continuation target: "
            f"{continuation.get('target_bucket', 'Not available')}"
        ),
        f"Move stage: {move_stage.get('stage', 'Not available')}",
        (
            "Move from recent low %: "
            f"{_format_pct(move_stage.get('move_from_recent_low_pct'))}"
        ),
        f"Liquidity label: {liquidity.get('label', 'Not available')}",
        f"Exhaustion risk: {exhaustion.get('risk_level', 'Not available')}",
        "",
        "Component scores:",
    ]
    lines.extend(_format_component_scores(component_scores))

    rejection_reasons = get_rejection_reasons(result, alert_threshold)
    if rejection_reasons:
        lines.extend(["", "Diagnostics:"])
        lines.extend(rejection_reasons)

    lines.extend(
        [
            "",
            "Recommendation:",
            get_recommendation(result, alert_threshold),
        ]
    )

    return "\n".join(lines)


def get_rejection_reasons(result: dict, alert_threshold: int = 60) -> list[str]:
    """Return diagnostic rejection and weak-confirmation reasons."""
    score = _get_opportunity_score(result)
    liquidity = result.get("liquidity_signal", {})
    exhaustion = result.get("exhaustion_signal", {})
    continuation = result.get("continuation_target", {})
    move_stage = result.get("move_stage_signal", {})
    volume_score = _get_signal_score(result.get("volume_signal"))
    breakout_score = _get_signal_score(result.get("breakout_signal"))
    move_from_recent_low_pct = _safe_float(
        move_stage.get("move_from_recent_low_pct")
    )
    reasons = []

    if score < alert_threshold:
        reasons.append("Rejected: score below alert threshold.")

    if liquidity.get("label") in {"Thin", "Very thin"}:
        reasons.append("Rejected/penalised: liquidity is thin.")

    if exhaustion.get("risk_level") == "High":
        reasons.append("Rejected/penalised: exhaustion risk is high.")

    if continuation.get("target_bucket") in NO_VALID_CONTINUATION_TARGETS:
        reasons.append("Rejected/penalised: no valid continuation target.")

    if volume_score < 40:
        reasons.append("Weak confirmation: volume expansion is insufficient.")

    if breakout_score == 0:
        reasons.append("Weak confirmation: no breakout confirmed.")

    if move_from_recent_low_pct > 20:
        reasons.append("Late move risk: price may already be extended.")

    return reasons


def get_recommendation(result: dict, alert_threshold: int = 60) -> str:
    """Return the final diagnostic recommendation."""
    score = _get_opportunity_score(result)

    if score >= alert_threshold:
        return "This symbol currently qualifies as an alert candidate."

    if alert_threshold - score <= 10:
        return "Near miss. Monitor if volume/breakout improves."

    return "Does not currently qualify."


def _fetch_symbol_ticker_24hr(client, symbol: str) -> dict:
    """Fetch 24-hour ticker data for one symbol from available client methods."""
    if hasattr(client, "get_24hr_ticker"):
        return client.get_24hr_ticker(symbol)

    if not hasattr(client, "get_24hr_tickers"):
        return {}

    for ticker in client.get_24hr_tickers():
        if ticker.get("symbol") == symbol:
            return ticker

    return {}


def _format_component_scores(component_scores: dict) -> list[str]:
    """Format component scores in a stable order."""
    if not component_scores:
        return ["- Not available"]

    ordered_names = [
        "volume",
        "momentum",
        "breakout",
        "trend",
        "volatility",
        "move_stage",
        "liquidity",
        "exhaustion_risk",
    ]
    lines = []

    for name in ordered_names:
        if name in component_scores:
            lines.append(f"- {name}: {component_scores[name]}")

    for name, value in component_scores.items():
        if name not in ordered_names:
            lines.append(f"- {name}: {value}")

    return lines


def _get_opportunity_score(result: dict) -> int:
    """Read the opportunity score safely."""
    try:
        return int(result.get("opportunity", {}).get("opportunity_score", 0))
    except (TypeError, ValueError):
        return 0


def _get_signal_score(signal: dict | None) -> int:
    """Read a standard signal score safely."""
    if not signal:
        return 0

    try:
        return int(signal.get("score", 0))
    except (TypeError, ValueError):
        return 0


def _safe_float(value) -> float:
    """Read a float safely."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _format_pct(value) -> str:
    """Format percentage values for diagnostic output."""
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "Not available"
