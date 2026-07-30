"""Fund screening and ranking."""

from __future__ import annotations

__all__ = ["ScreenerService"]


def __getattr__(name: str):
    if name == "ScreenerService":
        from services.screener.screener_service import ScreenerService

        return ScreenerService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
