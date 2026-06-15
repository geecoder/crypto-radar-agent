"""Telegram alert helpers."""

import time

import requests

from app.config import settings

TELEGRAM_MAX_MESSAGE_LENGTH = 4096
_RETRY_DELAYS = (2, 4, 8)


def send_telegram_message(message: str) -> bool:
    """Send a Telegram message when Telegram alerts are enabled."""
    if not settings.telegram_alerts_enabled:
        print("Telegram alerts disabled.")
        return False

    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        print("Telegram alerts enabled, but bot token or chat ID is missing.")
        return False

    # Split into chunks that fit within Telegram's 4096-char limit.
    chunks = _split_message(message)
    all_sent = True

    for chunk in chunks:
        sent = _send_with_retry(chunk)
        if not sent:
            all_sent = False

    return all_sent


def _split_message(message: str) -> list[str]:
    """Split a message into Telegram-safe chunks of at most 4096 chars."""
    if len(message) <= TELEGRAM_MAX_MESSAGE_LENGTH:
        return [message]

    chunks = []
    remaining = message

    while remaining:
        if len(remaining) <= TELEGRAM_MAX_MESSAGE_LENGTH:
            chunks.append(remaining)
            break

        # Break at the last newline within the limit so we don't cut mid-line.
        split_at = remaining.rfind("\n", 0, TELEGRAM_MAX_MESSAGE_LENGTH)

        if split_at <= 0:
            split_at = TELEGRAM_MAX_MESSAGE_LENGTH

        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip("\n")

    return chunks


def _send_with_retry(message: str) -> bool:
    """Attempt to send one message chunk with exponential-backoff retries."""
    url = (
        "https://api.telegram.org/"
        f"bot{settings.telegram_bot_token}/sendMessage"
    )

    for attempt, delay in enumerate((*_RETRY_DELAYS, None), start=1):
        success, should_retry = _attempt_send(url, message, attempt)

        if success:
            return True

        if not should_retry or delay is None:
            break

        print(f"Telegram retry in {delay}s (attempt {attempt}/{len(_RETRY_DELAYS) + 1})...")
        time.sleep(delay)

    return False


def _attempt_send(url: str, message: str, attempt: int) -> tuple[bool, bool]:
    """Make one HTTP POST attempt. Returns (success, should_retry)."""
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": message,
        "parse_mode": "HTML",
    }

    try:
        response = requests.post(url, data=payload, timeout=20)

        if response.status_code == 200:
            return True, False

        body = response.text[:500]
        print(
            f"Telegram send failed (attempt {attempt}): "
            f"HTTP {response.status_code} — {body}"
        )

        # 429 rate-limit: retry. 400/401/403: don't retry (config error).
        if response.status_code == 429:
            retry_after = _parse_retry_after(response)
            print(f"Telegram rate-limited. Retry-After: {retry_after}s")
            if retry_after:
                time.sleep(min(retry_after, 30))
            return False, True

        if response.status_code in {400, 401, 403}:
            print(
                "Telegram config error — check bot token, chat ID, and "
                "that the bot is not blocked or removed from the chat."
            )
            return False, False

        return False, True

    except requests.Timeout:
        print(f"Telegram send timed out (attempt {attempt}).")
        return False, True
    except requests.ConnectionError as error:
        print(f"Telegram connection error (attempt {attempt}): {error}")
        return False, True
    except requests.RequestException as error:
        print(f"Telegram request error (attempt {attempt}): {error}")
        return False, False


def _parse_retry_after(response: requests.Response) -> int | None:
    """Parse Retry-After seconds from a Telegram 429 response."""
    try:
        data = response.json()
        parameters = data.get("parameters") or {}
        return int(parameters.get("retry_after", 0)) or None
    except Exception:
        return None
