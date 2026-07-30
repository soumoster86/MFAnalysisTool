"""Every page file is reachable from the sidebar.

The app builds its navigation from an explicit `st.Page(...)` list rather than
Streamlit's automatic `pages/` discovery, so a new file under `frontend/pages/`
is reachable by URL but invisible in the sidebar until it is registered. That
failure is silent — the page works if you type its address — so it needs a test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "frontend" / "app.py"
PAGES_DIR = ROOT / "frontend" / "pages"


def _app_source() -> str:
    return APP.read_text(encoding="utf-8")


def _registered_pages() -> set[str]:
    """Page files named in an st.Page(...) call."""
    return set(re.findall(r'st\.Page\(\s*["\']pages/([^"\']+)["\']', _app_source()))


def _page_variables() -> set[str]:
    """Variable names assigned from st.Page(...)."""
    return set(
        re.findall(r'^(\w+)\s*=\s*st\.Page\(', _app_source(), flags=re.MULTILINE)
    )


def _grouped_variables() -> set[str]:
    """Variables placed into a st.navigation group."""
    match = re.search(r"st\.navigation\(\s*\{(.*?)\}\s*\)", _app_source(), flags=re.DOTALL)
    if not match:
        return set()
    return set(re.findall(r"\b(\w+)\b(?=\s*[,\]])", match.group(1)))


def _page_files() -> set[str]:
    return {p.name for p in PAGES_DIR.glob("*.py") if not p.name.startswith("_")}


def test_every_page_file_is_registered_in_navigation():
    missing = _page_files() - _registered_pages()
    assert not missing, (
        f"These pages exist but are not in st.navigation, so they will not "
        f"appear in the sidebar: {sorted(missing)}"
    )


def test_no_navigation_entry_points_at_a_missing_file():
    dangling = _registered_pages() - _page_files()
    assert not dangling, f"st.navigation references files that do not exist: {sorted(dangling)}"


def test_every_registered_page_is_placed_in_a_group():
    # A page can be registered and still never render in the sidebar if it is
    # left out of the navigation dict.
    ungrouped = _page_variables() - _grouped_variables()
    assert not ungrouped, (
        f"These pages are declared but not placed in a navigation group: "
        f"{sorted(ungrouped)}"
    )


def test_screener_is_reachable_from_the_sidebar():
    assert "18_Screener.py" in _registered_pages()
    assert "screener" in _grouped_variables()
