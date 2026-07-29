"""Data-source disclosure shared by every page that computes on NAV or holdings.

One renderer so the warning reads identically everywhere: a page must never
present a Sharpe ratio, a frontier or an allocation chart built on synthetic
NAV or sample holdings without saying so.
"""

from __future__ import annotations

from typing import Any, Optional, Union

import streamlit as st

from services.data.provenance import Provenance

__all__ = ["render_provenance", "provenance_for_codes"]


def _as_provenance(source: Union[Provenance, dict[str, Any], None]) -> Provenance:
    if isinstance(source, Provenance):
        return source
    return Provenance.from_dict(source)


def _fund_list(names: list[str], limit: int = 8) -> str:
    shown = names[:limit]
    extra = len(names) - len(shown)
    text = "\n".join(f"- {n}" for n in shown)
    if extra > 0:
        text += f"\n- …and {extra} more"
    return text


def render_provenance(
    source: Union[Provenance, dict[str, Any], None],
    *,
    what: str = "These figures",
    compact: bool = False,
) -> None:
    """Disclose the data sources behind the numbers on the current page.

    Renders a warning when any input was fabricated, otherwise a quiet caption.
    `what` names the affected output, e.g. "This frontier".
    """
    prov = _as_provenance(source)
    if prov.is_empty:
        return

    if prov.has_fabricated:
        bad_nav = prov.fabricated_nav
        bad_hold = prov.fabricated_holdings
        bits = []
        if bad_nav:
            bits.append(f"**{len(bad_nav)}** fund(s) on synthetic NAV")
        if bad_hold:
            bits.append(f"**{len(bad_hold)}** fund(s) on sample holdings")
        st.warning(
            f"{what} are partly computed from **fabricated data** — "
            + " and ".join(bits)
            + ". Live providers failed for these funds, so the values below will "
            "not match published returns. Treat them as illustrative only."
        )
        with st.expander("Which funds are affected?"):
            if bad_nav:
                st.markdown("**Synthetic NAV history**")
                st.markdown(_fund_list(bad_nav))
            if bad_hold:
                st.markdown("**Sample (not real) holdings**")
                st.markdown(_fund_list(bad_hold))
            st.caption(
                "Set `ALLOW_SYNTHETIC_NAV_FALLBACK=false` / "
                "`ALLOW_SAMPLE_HOLDINGS_FALLBACK=false` to fail loudly instead "
                "of substituting fabricated data."
            )
        return

    if compact:
        return

    parts = []
    nav_counts = prov.source_counts("nav")
    hold_counts = prov.source_counts("holdings")
    if nav_counts:
        parts.append("NAV " + ", ".join(f"`{k}`×{v}" for k, v in nav_counts.items()))
    if hold_counts:
        parts.append("Holdings " + ", ".join(f"`{k}`×{v}" for k, v in hold_counts.items()))
    if parts:
        stale = prov.stale_nav
        suffix = f" · {len(stale)} served from a stale cache" if stale else ""
        st.caption("Data sources — " + " · ".join(parts) + suffix)


def provenance_for_codes(
    fund_service: Any,
    holdings: Optional[list[dict[str, Any]]] = None,
    *,
    entries: Optional[list[tuple[str, str]]] = None,
    include_holdings: bool = True,
) -> Provenance:
    """Build a Provenance from session holdings or explicit (label, code) pairs."""
    if entries is None:
        entries = [
            (str(h.get("scheme_name") or h.get("amfi_code") or ""), str(h.get("amfi_code") or ""))
            for h in (holdings or [])
        ]
    return Provenance.from_service(fund_service, entries, include_holdings=include_holdings)
