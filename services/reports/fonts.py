"""Font resolution for PDF output.

reportlab's built-in Helvetica has no rupee glyph. It still reports a width for
U+20B9, so nothing errors — the character just renders as a hollow box, and
every currency figure in the report looks broken.

Look for a Unicode TTF in the usual places and register it. When none is found
(a slim container, say), fall back to writing "Rs" instead of the symbol: an
honest ASCII prefix beats a box.
"""

from __future__ import annotations

import glob
import os
from functools import lru_cache
from typing import Optional

from utils.logging_config import get_logger

logger = get_logger(__name__)

RUPEE = "\u20b9"

# Ordered by preference. DejaVu ships with matplotlib and most Linux images;
# the Windows and macOS entries cover local development.
_CANDIDATES: list[tuple[str, str]] = [
    ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
    ("dejavu/DejaVuSans.ttf", "dejavu/DejaVuSans-Bold.ttf"),
    ("segoeui.ttf", "segoeuib.ttf"),
    ("arialuni.ttf", "arialuni.ttf"),
]

_SEARCH_DIRS: list[str] = [
    "/usr/share/fonts/truetype",
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts",
    "C:/Windows/Fonts",
    "/Library/Fonts",
    "/System/Library/Fonts/Supplemental",
]


def _matplotlib_font_dir() -> Optional[str]:
    try:
        import matplotlib

        return os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data", "fonts", "ttf")
    except Exception:
        return None


def _find(filename: str) -> Optional[str]:
    dirs = list(_SEARCH_DIRS)
    mpl_dir = _matplotlib_font_dir()
    if mpl_dir:
        dirs.insert(0, mpl_dir)
    for directory in dirs:
        candidate = os.path.join(directory, filename)
        if os.path.exists(candidate):
            return candidate
        hits = glob.glob(os.path.join(directory, "**", os.path.basename(filename)), recursive=True)
        if hits:
            return hits[0]
    return None


@lru_cache(maxsize=1)
def register_unicode_font() -> tuple[str, str, bool]:
    """(regular, bold, supports_rupee) font names for the PDF renderer."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for regular_file, bold_file in _CANDIDATES:
        regular = _find(regular_file)
        if not regular:
            continue
        bold = _find(bold_file) or regular
        try:
            pdfmetrics.registerFont(TTFont("ReportSans", regular))
            pdfmetrics.registerFont(TTFont("ReportSans-Bold", bold))
            pdfmetrics.registerFontFamily(
                "ReportSans", normal="ReportSans", bold="ReportSans-Bold"
            )
            logger.info("PDF font: {}", regular)
            return "ReportSans", "ReportSans-Bold", True
        except Exception as exc:
            logger.debug("Could not register {}: {}", regular, exc)

    logger.warning(
        "No Unicode TTF found for PDF output; falling back to Helvetica and "
        "writing 'Rs' instead of the rupee sign."
    )
    return "Helvetica", "Helvetica-Bold", False


def money_text(formatted: str) -> str:
    """Swap the rupee sign for 'Rs' when the active font cannot draw it."""
    _, _, supports = register_unicode_font()
    if supports:
        return formatted
    return formatted.replace(RUPEE, "Rs ")
