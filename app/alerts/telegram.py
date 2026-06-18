"""Telegram alert helpers."""

import time
from typing import NamedTuple

import requests

from app.config import settings

TELEGRAM_MAX_MESSAGE_LENGTH = 4096
_RETRY_DELAYS = (2, 4, 8)
# Telegram allows ~1 msg/sec to the same chat
_INTER_CHUNK_DELAY = 1.1


class TelegramAttempt(NamedTuple):
    attempt_number: int
    http_status: int | None   # None on network error
    response_body: str | None
    success: bool


def send_telegram_message(message: str) -> tuple[bool, list[TelegramAttempt]]:
    """Send a Telegram message when Telegram alerts are enabled.

    Returns (all_sent, attempts) where attempts contains structured per-HTTP-call
    diagnostics suitable for writing to telegram_send_log.
    """
    if not settings.telegram_alerts_enabled:
        print("Telegram alerts disabled.")
        return False, []

    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        print("Telegram alerts enabled, but bot token or chat ID is missing.")
        return False, []

    chunks = _split_message(message)
    all_sent = True
    all_attempts: list[TelegramAttempt] = []

    for i, chunk in enumerate(chunks):
        if i > 0:
            # Respect Telegram's 1 msg/sec limit to the same chat
            time.sleep(_INTER_CHUNK_DELAY)

        sent, attempts = _send_with_retry(chunk)
        all_attempts.extend(attempts)

        if not sent:
            all_sent = False

    return all_sent, all_attempts


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


def _send_with_retry(message: str) -> tuple[bool, list[TelegramAttempt]]:
    """Attempt to send one message chunk with exponential-backoff retries."""
    url = (
        "https://api.telegram.org/"
        f"bot{settings.telegram_bot_token}/sendMessage"
    )
    attempts: list[TelegramAttempt] = []

    for attempt, delay in enumerate((*_RETRY_DELAYS, None), start=1):
        success, should_retry, http_status, response_body = _attempt_send(
            url, message, attempt
        )
        attempts.append(
            TelegramAttempt(
                attempt_number=attempt,
                http_status=http_status,
                response_body=response_body,
                success=success,
            )
        )

        if success:
            return True, attempts

        if not should_retry or delay is None:
            break

        print(f"Telegram retry in {delay}s (attempt {attempt}/{len(_RETRY_DELAYS) + 1})...")
        time.sleep(delay)

    return False, attempts


def _attempt_send(
    url: str, message: str, attempt: int
) -> tuple[bool, bool, int | None, str | None]:
    """Make one HTTP POST attempt.

    Returns (success, should_retry, http_status, response_body).
    http_status and response_body are None on network-level errors.
    """
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": message,
        "parse_mode": "HTML",
    }

    try:
        response = requests.post(url, data=payload, timeout=20)
        body = response.text[:500]

        if response.status_code == 200:
            return True, False, 200, body

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
            return False, True, 429, body

        if response.status_code in {400, 401, 403}:
            print(
                "Telegram config error — check bot token, chat ID, and "
                "that the bot is not blocked or removed from the chat."
            )
            return False, False, response.status_code, body

        return False, True, response.status_code, body

    except requests.Timeout:
        print(f"Telegram send timed out (attempt {attempt}).")
        return False, True, None, "Timeout"
    except requests.ConnectionError as error:
        print(f"Telegram connection error (attempt {attempt}): {error}")
        return False, True, None, f"ConnectionError: {str(error)[:200]}"
    except requests.RequestException as error:
        print(f"Telegram request error (attempt {attempt}): {error}")
        return False, False, None, f"RequestException: {str(error)[:200]}"


def _parse_retry_after(response: requests.Response) -> int | None:
    """Parse Retry-After seconds from a Telegram 429 response."""
    try:
        data = response.json()
        parameters = data.get("parameters") or {}
        return int(parameters.get("retry_after", 0)) or None
    except Exception:
        return None
