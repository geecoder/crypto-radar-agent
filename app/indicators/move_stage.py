"""Move-stage signal indicators."""


def calculate_move_stage(df, lookback: int = 96) -> dict:
    """Measure how far price has moved from its recent low."""
    if df.empty:
        return {
            "name": "move_stage",
            "lookback": lookback,
            "latest_close": 0.0,
            "recent_low": 0.0,
            "move_from_recent_low_pct": 0.0,
            "stage": "No move",
            "score": 0,
            "reason": "Not enough candle data to calculate move stage.",
        }

    latest_close = float(df["close"].iloc[-1])
    recent_low = float(df["low"].tail(lookback).min())

    if recent_low <= 0:
        return {
            "name": "move_stage",
            "lookback": lookback,
            "latest_close": latest_close,
            "recent_low": recent_low,
            "move_from_recent_low_pct": 0.0,
            "stage": "No move",
            "score": 0,
            "reason": "Recent low is zero, so move stage cannot be calculated.",
        }

    move_pct = ((latest_close - recent_low) / recent_low) * 100
    stage, score = _classify_move(move_pct)

    return {
        "name": "move_stage",
        "lookback": lookback,
        "latest_close": latest_close,
        "recent_low": recent_low,
        "move_from_recent_low_pct": move_pct,
        "stage": stage,
        "score": score,
        "reason": (
            f"Price is {move_pct:.2f}% above the recent {lookback}-candle low."
        ),
    }


def _classify_move(move_pct: float) -> tuple[str, int]:
    """Classify the percentage move into a stage and score."""
    if move_pct < 0:
        return "No move", 0
    if move_pct < 3:
        return "Stage 1 - Very early move", 40
    if move_pct < 7:
        return "Stage 2 - Early momentum", 70
    if move_pct < 10:
        return "Stage 3 - Confirmed early momentum", 90
    if move_pct < 20:
        return "Stage 4 - Active momentum", 75
    if move_pct < 50:
        return "Stage 5 - Extended move", 45
    return "Stage 6 - Parabolic / high risk", 20
