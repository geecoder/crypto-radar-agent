"""Logging helpers."""

import logging

from app.config import settings


def get_logger(name: str) -> logging.Logger:
    """Return a logger configured with the project log level."""
    logging.basicConfig(level=settings.log_level)
    return logging.getLogger(name)
