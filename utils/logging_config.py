"""Structured logging setup using loguru with stdlib fallback."""

from __future__ import annotations

import logging
import sys
from typing import Optional

from loguru import logger


class InterceptHandler(logging.Handler):
    """Redirect standard logging to loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logging(level: str = "INFO") -> None:
    """Configure application-wide logging."""
    logger.remove()
    logger.add(
        sys.stderr,
        level=level.upper(),
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan> - "
            "<level>{message}</level>"
        ),
        colorize=True,
    )
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)


def get_logger(name: Optional[str] = None):
    """Return a loguru logger bound with optional name."""
    return logger.bind(name=name) if name else logger
