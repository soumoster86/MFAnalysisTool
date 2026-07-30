"""Shared visual identity for generated reports.

One palette across PDF, Excel and PowerPoint so the three files look like they
came from the same product. Hex strings here; each renderer converts to its own
colour type.
"""

from __future__ import annotations

# Matches the app's dark theme accent, on a light document background — a
# report gets printed and read on paper far more often than a dashboard does.
INK = "1B2430"          # headings, primary text
MUTED = "5C6B7A"        # captions, secondary text
RULE = "D8DEE6"         # hairlines, table grid
BAND = "F4F7FA"         # zebra rows, panel fill
ACCENT = "16A34A"       # brand green
ACCENT_DARK = "0F7A34"
POSITIVE = "16A34A"
NEGATIVE = "DC2626"
WARNING_FILL = "FEF3C7"
WARNING_INK = "92400E"

# Categorical series for allocation charts, ordered for contrast.
SERIES = [
    "16A34A",
    "2563EB",
    "F59E0B",
    "8B5CF6",
    "EC4899",
    "06B6D4",
    "EF4444",
    "84CC16",
    "6366F1",
    "F97316",
    "14B8A6",
    "A855F7",
]

FOOTER_NOTE = (
    "Educational analysis only. Not investment advice, and not a recommendation "
    "to buy or sell. Past performance does not predict future returns."
)


def tone_colour(tone: str) -> str:
    return {"good": POSITIVE, "bad": NEGATIVE}.get(tone, INK)


def series_colour(index: int) -> str:
    return SERIES[index % len(SERIES)]
