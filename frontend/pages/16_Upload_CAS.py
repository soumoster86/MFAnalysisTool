"""Upload MFCentral CAS Summary PDF → portfolio holdings."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from frontend.state import (
    get_active_portfolio_id,
    get_fund_service,
    is_logged_in,
    save_session_to_vault,
    set_portfolio_holdings,
)
from frontend.components.page import page_header
from frontend.theme import apply_theme
from services.portfolio.import_service import PortfolioImportService
from utils.helpers import format_inr

apply_theme()

page_header(
    "Upload MF Holdings (MFCentral CAS)",
    "Import your MFCentral Consolidated Account Summary PDF — SoA + Demat holdings "
    "map to AMFI schemes and feed Dashboard / Portfolio Analyzer.",
    "📤",
)

st.info(
    "**Privacy:** PAN is masked in the UI. Only scheme holdings (units, invested, market value) "
    "are kept in session for analysis. Prefer removing personal PDFs from shared machines after import.",
    icon="🔒",
)

with st.expander("How to get your CAS PDF", expanded=False):
    st.markdown(
        """
1. Open [MFCentral](https://www.mfcentral.com/) and log in / request CAS.  
2. Download **Consolidated Account Summary** PDF (this app targets `MFCentralCASSummary_v2.x`).  
3. Upload the file below (PDF).  
4. Review matched schemes → **Apply to portfolio**.  
5. Open **Dashboard** or **Portfolio Analyzer** to run analytics.

Also supported later: CSV/Excel with columns  
`scheme_name, units, invested_amount, amfi_code (optional)`.
"""
    )

uploaded = st.file_uploader(
    "MFCentral CAS Summary PDF",
    type=["pdf"],
    help="Example: cas_summary_report_YYYY_MM_DD_HHMMSS.pdf",
)

c1, c2, c3 = st.columns(3)
with c1:
    include_soa = st.checkbox("Include SoA holdings", value=True)
with c2:
    include_demat = st.checkbox("Include Demat holdings", value=True)
with c3:
    merge_dupes = st.checkbox("Merge same scheme (SoA+Demat)", value=True)

min_score = st.slider("Min AMFI match confidence", 0.30, 0.80, 0.45, 0.05)

if uploaded is not None and st.button("Parse & map holdings", type="primary"):
    data = uploaded.getvalue()
    with st.spinner("Parsing PDF and resolving AMFI codes (may take a minute)…"):
        try:
            svc = PortfolioImportService(get_fund_service())
            result = svc.import_cas_pdf(
                data,
                filename=uploaded.name,
                include_soa=include_soa,
                include_demat=include_demat,
                merge_duplicates=merge_dupes,
                min_match_score=float(min_score),
            )
            st.session_state["cas_import_result"] = result
            st.success(
                f"Parsed {result.cas.get('holdings_count', 0)} CAS lines → "
                f"{len(result.holdings)} portfolio rows "
                f"({result.merged_count} merges, {len(result.unmatched)} unmatched)"
            )
        except Exception as exc:
            st.error(f"Import failed: {exc}")
            st.stop()

result = st.session_state.get("cas_import_result")
if not result:
    st.markdown("---")
    st.subheader("Or paste a CSV of holdings")
    sample_csv = (
        "scheme_name,units,invested_amount,amfi_code\n"
        "Parag Parikh Flexi Cap Fund - Direct Plan - Growth,100,50000,\n"
    )
    csv_text = st.text_area("CSV", value=sample_csv, height=120)
    if st.button("Import CSV"):
        try:
            from io import StringIO

            df = pd.read_csv(StringIO(csv_text))
            rows = []
            importer = PortfolioImportService(get_fund_service())
            for _, r in df.iterrows():
                name = str(r.get("scheme_name", "")).strip()
                code = str(r.get("amfi_code", "") or "").strip()
                if not code and name:
                    m = importer.resolve_scheme(name)
                    if m:
                        code, name = m[0], m[1]
                rows.append(
                    {
                        "amfi_code": code,
                        "scheme_name": name,
                        "invested_amount": float(r.get("invested_amount") or 0),
                        "units": float(r.get("units") or 0),
                        "sip_amount": 0,
                    }
                )
            st.session_state["cas_csv_rows"] = rows
            st.success(f"Prepared {len(rows)} rows from CSV")
        except Exception as exc:
            st.error(str(exc))

    if st.session_state.get("cas_csv_rows"):
        st.dataframe(st.session_state["cas_csv_rows"], use_container_width=True)
        if st.button("Apply CSV to portfolio"):
            set_portfolio_holdings(st.session_state["cas_csv_rows"])
            st.success("Portfolio updated from CSV. Open Dashboard / Analyzer.")
    st.stop()

# --- Show CAS meta ---
cas = result.cas
m1, m2, m3, m4 = st.columns(4)
m1.metric("As on", cas.get("as_on_date") or "—")
m2.metric("Investor", cas.get("investor_name") or "—")
m3.metric("PAN", cas.get("pan_masked") or "—")
m4.metric("Market value (CAS)", format_inr(cas.get("total_market_value") or 0))

c1, c2 = st.columns(2)
c1.metric("SoA total (PDF)", format_inr(cas.get("soa_total") or 0))
c2.metric("Demat total (PDF)", format_inr(cas.get("demat_total") or 0))

if result.warnings:
    with st.expander(f"Warnings ({len(result.warnings)})", expanded=False):
        for w in result.warnings[:40]:
            st.write(f"- {w}")

# --- Editable match table ---
st.subheader("Mapped holdings")
rows = []
for h in result.holdings:
    rows.append(
        {
            "include": bool(h.amfi_code),
            "amfi_code": h.amfi_code,
            "scheme_name": h.scheme_name,
            "cas_name": h.cas_scheme_name,
            "units": h.units,
            "invested_amount": h.invested_amount,
            "market_value": h.market_value,
            "nav": h.current_nav,
            "type": h.holding_type,
            "match": f"{h.match_method} ({h.match_score:.0%})"
            if h.amfi_code
            else "unmatched",
        }
    )

edited = st.data_editor(
    pd.DataFrame(rows),
    use_container_width=True,
    hide_index=True,
    column_config={
        "include": st.column_config.CheckboxColumn("Use", default=True),
        "amfi_code": st.column_config.TextColumn("AMFI code"),
        "scheme_name": st.column_config.TextColumn("Resolved scheme", width="large"),
        "cas_name": st.column_config.TextColumn("CAS name", width="medium"),
        "units": st.column_config.NumberColumn("Units", format="%.4f"),
        "invested_amount": st.column_config.NumberColumn("Invested ₹", format="%.2f"),
        "market_value": st.column_config.NumberColumn("Market ₹", format="%.2f"),
        "nav": st.column_config.NumberColumn("NAV", format="%.4f"),
    },
    disabled=["cas_name", "match", "type"],
    num_rows="fixed",
)

a1, a2, a3 = st.columns(3)
with a1:
    apply = st.button("Apply to portfolio", type="primary", use_container_width=True)
with a2:
    apply_matched = st.button(
        "Apply matched only", use_container_width=True
    )
with a3:
    if st.button("Clear import", use_container_width=True):
        st.session_state.pop("cas_import_result", None)
        st.rerun()

def _rows_to_portfolio(df: pd.DataFrame, matched_only: bool = False) -> list[dict]:
    out = []
    for _, r in df.iterrows():
        if not r.get("include", True):
            continue
        code = str(r.get("amfi_code") or "").strip()
        if matched_only and not code:
            continue
        if not code:
            continue
        invested = float(r.get("invested_amount") or 0)
        mkt = float(r.get("market_value") or 0)
        nav = r.get("nav")
        try:
            nav_f = float(nav) if nav is not None and str(nav) not in ("", "nan") else None
        except (TypeError, ValueError):
            nav_f = None
        if invested <= 0 and mkt > 0:
            invested = mkt
        out.append(
            {
                "amfi_code": code,
                "scheme_name": str(r.get("scheme_name") or ""),
                "invested_amount": invested,
                "units": float(r.get("units") or 0),
                "sip_amount": 0.0,
                # Carry CAS valuation so analyzer can skip re-pricing network calls
                "market_value": mkt if mkt > 0 else None,
                "current_nav": nav_f,
                "nav": nav_f,
            }
        )
    return out

if apply or apply_matched:
    portfolio = _rows_to_portfolio(edited, matched_only=True)
    if not portfolio:
        st.error("No rows with AMFI codes to apply. Fix unmatched schemes first.")
    else:
        set_portfolio_holdings(portfolio)
        st.session_state["portfolio_source"] = "mfcentral_cas"
        total_mkt = sum(float(p.get("market_value") or p.get("invested_amount") or 0) for p in portfolio)
        total_inv = sum(float(p.get("invested_amount") or 0) for p in portfolio)
        st.success(
            f"Applied **{len(portfolio)}** schemes (≈ {format_inr(total_mkt)} market value). "
            "Open **Dashboard** or **Portfolio Analyzer** — analysis runs in fast mode for large portfolios."
        )
        # Lightweight summary from CAS numbers only (no network storm)
        k1, k2, k3 = st.columns(3)
        k1.metric("Schemes applied", len(portfolio))
        k2.metric("Invested (CAS)", format_inr(total_inv))
        k3.metric("Market value (CAS)", format_inr(total_mkt))

        # ---- Vault save (Slice A) ----
        as_of = (result.cas or {}).get("as_of_date") if result else None
        if is_logged_in():
            st.markdown("#### Save to portfolio vault")
            vc1, vc2 = st.columns([2, 1])
            with vc1:
                vault_name = st.text_input(
                    "Vault name",
                    value=f"CAS {as_of or 'import'}",
                    key="cas_vault_name",
                )
            with vc2:
                update_active = st.checkbox(
                    "Update active portfolio",
                    value=bool(get_active_portfolio_id()),
                    key="cas_update_active",
                )
            if st.button("Save CAS portfolio to vault", type="primary", key="cas_save_vault"):
                try:
                    saved = save_session_to_vault(
                        name=vault_name,
                        portfolio_id=get_active_portfolio_id() if update_active else None,
                        source="cas_import",
                        as_of_date=as_of,
                        description="Imported from MFCentral CAS Summary",
                    )
                    st.success(
                        f"Saved to vault as **{saved['name']}** (#{saved['id']}). "
                        "Reopen anytime under **My Portfolios**."
                    )
                except Exception as exc:
                    st.error(str(exc))
        else:
            st.info("Sign in under **Account** to save this CAS portfolio permanently.")

        st.caption(
            "Deep risk/overlap charts load when you open Dashboard / Analyzer "
            "(cached after first run so the page stays responsive)."
        )
        st.dataframe(
            pd.DataFrame(portfolio)[
                [c for c in ["scheme_name", "amfi_code", "units", "invested_amount", "market_value", "current_nav"] if c in pd.DataFrame(portfolio).columns]
            ].head(30),
            use_container_width=True,
            hide_index=True,
        )

if result.unmatched:
    st.subheader("Unmatched schemes")
    st.caption("Edit AMFI codes in the table above, or search the Fund Database for the right code.")
    st.dataframe(result.unmatched, use_container_width=True, hide_index=True)
