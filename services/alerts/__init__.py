"""Alert services (Slice B).

Keep this package init lightweight — avoid eager imports that break on
Streamlit multipage load (circular / partial init).
"""

from __future__ import annotations

__all__ = [
    "AlertService",
    "AlertEngine",
    "default_rules",
    "known_alert_types",
]


def __getattr__(name: str):
    if name == "AlertService":
        from services.alerts.alert_service import AlertService

        return AlertService
    if name == "AlertEngine":
        from services.alerts.engine import AlertEngine

        return AlertEngine
    if name in ("default_rules", "known_alert_types"):
        from services.alerts import rules as _rules

        return getattr(_rules, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
