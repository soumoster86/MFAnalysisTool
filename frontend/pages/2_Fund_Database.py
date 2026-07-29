"""Module 2 — Mutual Fund Database."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from frontend.state import get_fund_service
from frontend.theme import apply_theme

apply_theme()

st.title("Mutual Fund Database")
st.caption("Live AMFI scheme master · categories inferred from scheme names")

svc = get_fund_service()

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    q = st.text_input("Search scheme or AMFI code", placeholder="e.g. Parag Parikh Flexi or 122639")
with col2:
    cat = st.selectbox("Category", ["All", "Equity", "Debt", "Hybrid", "Index/ETF", "Other"])
with col3:
    limit = st.number_input("Limit", 10, 500, 50, 10)

c1, c2 = st.columns(2)
with c1:
    if st.button("🔄 Refresh AMFI feed", use_container_width=True):
        with st.spinner("Downloading NAVAll.txt…"):
            try:
                df = svc.amfi.load(force_refresh=True)
                n = svc.sync_amfi_to_db(limit=500, force=False)
                st.success(f"Loaded {len(df)} schemes · synced {n} to SQLite")
            except Exception as exc:
                st.error(str(exc))
with c2:
    if st.button("📦 Sync top schemes to DB", use_container_width=True):
        with st.spinner("Upserting…"):
            n = svc.sync_amfi_to_db(limit=int(limit) * 4)
            st.success(f"Synced {n} funds")

with st.spinner("Loading schemes…"):
    try:
        results = svc.search_funds(
            q,
            category=None if cat == "All" else cat,
            limit=int(limit),
            direct_growth_only=st.checkbox("Direct Growth only", value=True),
        )
    except Exception as exc:
        st.error(f"Failed to load funds: {exc}")
        st.stop()

st.metric("Results", len(results))
show_cols = [c for c in ["amfi_code", "scheme_name", "amc", "category", "subcategory", "nav", "nav_date"] if c in results.columns]
st.dataframe(results[show_cols], use_container_width=True, hide_index=True)

if not results.empty:
    st.subheader("Scheme detail")
    pick = st.selectbox("Select scheme", results["scheme_name"].tolist())
    row = results[results["scheme_name"] == pick].iloc[0]
    # Human-readable field cards instead of raw JSON
    detail = {k: ("" if v is None or (isinstance(v, float) and pd.isna(v)) else v) for k, v in row.to_dict().items()}
    nice_labels = {
        "amfi_code": "AMFI code",
        "scheme_name": "Scheme",
        "amc": "AMC",
        "category": "Category",
        "subcategory": "Sub-category",
        "nav": "Latest NAV",
        "nav_date": "NAV date",
        "isin_growth": "ISIN (growth)",
        "isin_div": "ISIN (div)",
    }
    cols = st.columns(3)
    shown = 0
    for key, label in nice_labels.items():
        if key in detail and detail[key] not in ("", None):
            cols[shown % 3].metric(label, str(detail[key])[:48])
            shown += 1
    with st.expander("All fields"):
        st.dataframe(
            pd.DataFrame(
                [{"Field": nice_labels.get(k, k), "Value": str(v)} for k, v in detail.items() if v not in ("", None)]
            ),
            use_container_width=True,
            hide_index=True,
        )

    code = str(row["amfi_code"])
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Fetch real NAV history", use_container_width=True):
            with st.spinner("mfapi.in / TigZig…"):
                try:
                    info = svc.prefetch_fund(code, years=5.0, force=True)
                    st.success(
                        f"NAV: {info['nav_points']} pts ({info['nav_source']}) "
                        f"{info['nav_start']} → {info['nav_end']}"
                    )
                    st.info(
                        f"Holdings: {info['holdings_rows']} rows ({info['holdings_source']})"
                    )
                except Exception as exc:
                    st.error(str(exc))
    with c2:
        if st.button("Fetch live holdings", use_container_width=True):
            with st.spinner("Groww holdings…"):
                try:
                    hdf = svc.get_holdings(code, row["scheme_name"], force_refresh=True)
                    st.success(
                        f"{len(hdf)} holdings · source={svc.get_holdings_source(code)}"
                    )
                    st.dataframe(hdf.head(20), use_container_width=True, hide_index=True)
                except Exception as exc:
                    st.error(str(exc))
    with c3:
        if st.button("Refresh holdings (live→DB)", use_container_width=True):
            svc.seed_demo_holdings([code])
            st.success("Holdings refresh attempted (live preferred, sample fallback)")
