"""Page chrome shared by every screen.

Each page previously opened with a bare `st.title` plus a `st.caption`, which
Streamlit stacks with uneven spacing and no separation from the content below.
These helpers give one header treatment and one empty state, so pages differ in
what they show rather than in how they are framed.
"""

from __future__ import annotations

import html
from typing import Optional

import streamlit as st

__all__ = ["page_header", "empty_state", "section"]


def page_header(title: str, subtitle: str = "", icon: str = "") -> None:
    """Title, optional subtitle and icon, with a rule beneath."""
    icon_html = f'<div class="ph-icon">{html.escape(icon)}</div>' if icon else ""
    sub_html = (
        f'<p class="ph-sub">{html.escape(subtitle)}</p>' if subtitle else ""
    )
    st.markdown(
        f'<div class="page-head">{icon_html}'
        f'<div><h1 class="ph-title">{html.escape(title)}</h1>{sub_html}</div></div>',
        unsafe_allow_html=True,
    )


def empty_state(
    title: str,
    body: str = "",
    icon: str = "📭",
    action_label: Optional[str] = None,
    action_page: Optional[str] = None,
) -> None:
    """A styled placeholder for 'nothing to show yet'.

    `action_page` takes a Streamlit page path so the placeholder can send the
    user where the missing data comes from, rather than only telling them.
    """
    st.markdown(
        f'<div class="empty-state">'
        f'<span class="es-icon">{html.escape(icon)}</span>'
        f'<span class="es-title">{html.escape(title)}</span>'
        f'<div>{html.escape(body)}</div></div>',
        unsafe_allow_html=True,
    )
    if action_label and action_page:
        try:
            st.page_link(action_page, label=action_label, icon="➡️")
        except Exception:
            # page_link needs a registered page; never break the placeholder.
            st.caption(action_label)


def section(title: str, caption: str = "") -> None:
    """A subheading with an optional one-line explanation."""
    st.subheader(title)
    if caption:
        st.caption(caption)
