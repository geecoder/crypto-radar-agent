"""Telegram alert helpers."""

import requests

from app.config import settings


def send_telegram_message(message: str) -> bool:
    """Send a Telegram message when Telegram alerts are enabled."""
    if not settings.telegram_alerts_enabled:
        print("Telegram alerts disabled.")
        return False

    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        print("Telegram alerts enabled, but bot token or chat ID is missing.")
        return False

    url = (
        "https://api.telegram.org/"
        f"bot{settings.telegram_bot_token}/sendMessage"
    )
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": message,
        "parse_mode": "HTML",
    }

    try:
        response = requests.post(url, data=payload, timeout=20)
        response.raise_for_status()
        return True
    except requests.RequestException as error:
        print(f"Failed to send Telegram message: {error}")
        return False
