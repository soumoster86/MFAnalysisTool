"""Module 2 — Mutual Fund Database (+ rich NAV history visualization)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from frontend.components.charts import (
    drawdown_chart,
    nav_history_caption,
    nav_history_chart,
    nav_history_stats,
)
from frontend.components.ui_blocks import insight_cards
from frontend.state import get_fund_service
from frontend.theme import apply_theme
from services.data.market_client import get_market_client
from utils.helpers import pct

apply_theme()

st.title("Mutual Fund Database")
st.caption("Live AMFI scheme master · historical NAV charts · holdings preview")

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
show_cols = [
    c
    for c in ["amfi_code", "scheme_name", "amc", "category", "subcategory", "nav", "nav_date"]
    if c in results.columns
]
st.dataframe(results[show_cols], use_container_width=True, hide_index=True)

if results.empty:
    st.stop()

st.subheader("Scheme detail")
pick = st.selectbox("Select scheme", results["scheme_name"].tolist())
row = results[results["scheme_name"] == pick].iloc[0]
detail = {
    k: ("" if v is None or (isinstance(v, float) and pd.isna(v)) else v)
    for k, v in row.to_dict().items()
}
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
            [
                {"Field": nice_labels.get(k, k), "Value": str(v)}
                for k, v in detail.items()
                if v not in ("", None)
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

code = str(row["amfi_code"])
scheme_name = str(row.get("scheme_name") or code)

# Persist last-fetched series per scheme in session
if "nav_viz_cache" not in st.session_state:
    st.session_state["nav_viz_cache"] = {}
if "holdings_viz_cache" not in st.session_state:
    st.session_state["holdings_viz_cache"] = {}

c1, c2, c3 = st.columns(3)
with c1:
    fetch_nav = st.button("Fetch real NAV history", use_container_width=True, type="primary")
with c2:
    fetch_hold = st.button("Fetch live holdings", use_container_width=True)
with c3:
    if st.button("Refresh holdings (live→DB)", use_container_width=True):
        svc.seed_demo_holdings([code])
        st.success("Holdings refresh attempted (live preferred, sample fallback)")

if fetch_nav:
    with st.spinner("Loading NAV history (mfapi / TigZig)…"):
        try:
            info = svc.prefetch_fund(code, years=5.0, force=True)
            nav = svc.get_nav_history(code, scheme_name, years=5.0, force_refresh=False)
            st.session_state["nav_viz_cache"][code] = {
                "nav": nav,
                "info": info,
                "source": info.get("nav_source") or svc.get_nav_source(code),
            }
            st.success(
                f"Loaded {info['nav_points']} points ({info['nav_source']}) · "
                f"{info['nav_start']} → {info['nav_end']}"
            )
        except Exception as exc:
            st.error(str(exc))

if fetch_hold:
    with st.spinner("Groww holdings…"):
        try:
            hdf = svc.get_holdings(code, scheme_name, force_refresh=True)
            st.session_state["holdings_viz_cache"][code] = {
                "df": hdf,
                "source": svc.get_holdings_source(code),
            }
            st.success(f"{len(hdf)} holdings · source={svc.get_holdings_source(code)}")
        except Exception as exc:
            st.error(str(exc))

# Auto-load NAV from memory cache if user already fetched / app has it
if code not in st.session_state["nav_viz_cache"]:
    try:
        # Use in-memory fund service cache without force (no extra network if warm)
        if code in getattr(svc, "_nav_cache", {}):
            nav = svc.get_nav_history(code, scheme_name, years=5.0)
            st.session_state["nav_viz_cache"][code] = {
                "nav": nav,
                "info": {
                    "nav_points": len(nav),
                    "nav_source": svc.get_nav_source(code),
                    "nav_start": str(nav.index.min().date()) if len(nav) else None,
                    "nav_end": str(nav.index.max().date()) if len(nav) else None,
                },
                "source": svc.get_nav_source(code),
            }
    except Exception:
        pass

# ---------- NAV HISTORY VISUALIZATION ----------
nav_bundle = st.session_state["nav_viz_cache"].get(code)
if nav_bundle and nav_bundle.get("nav") is not None and len(nav_bundle["nav"]) >= 2:
    st.markdown("---")
    st.subheader("NAV history")
    st.caption(
        "Green fill = positive period return · red = negative. "
        "Peak / trough markers and optional moving average help read the path."
    )

    nav_full = nav_bundle["nav"]
    source = nav_bundle.get("source") or "unknown"

    r1, r2, r3, r4 = st.columns([1.2, 1, 1, 1])
    with r1:
        period = st.selectbox(
            "Period",
            ["Max", "5Y", "3Y", "1Y", "6M"],
            index=0,
            key=f"nav_period_{code}",
        )
    with r2:
        show_ma = st.checkbox("Moving average", value=True, key=f"nav_ma_{code}")
    with r3:
        normalize = st.checkbox("Normalize (base 100)", value=False, key=f"nav_norm_{code}")
    with r4:
        show_dd = st.checkbox("Show drawdown", value=True, key=f"nav_dd_{code}")

    # Slice period
    s = nav_full.dropna().astype(float).sort_index()
    if not isinstance(s.index, pd.DatetimeIndex):
        s.index = pd.to_datetime(s.index)
    end = s.index.max()
    cut = {
        "6M": pd.DateOffset(months=6),
        "1Y": pd.DateOffset(years=1),
        "3Y": pd.DateOffset(years=3),
        "5Y": pd.DateOffset(years=5),
        "Max": None,
    }[period]
    nav_view = s if cut is None else s[s.index >= (end - cut)]

    stats = nav_history_stats(nav_view)
    if stats:
        insight_cards(
            [
                {
                    "label": "Latest NAV",
                    "value": f"{stats['latest_nav']:.4f}",
                    "help": f"As of {stats['end']:%d %b %Y}",
                    "tone": "neutral",
                },
                {
                    "label": "Period return",
                    "value": f"{stats['period_return']*100:+.1f}%",
                    "help": f"{stats['start']:%Y-%m-%d} → {stats['end']:%Y-%m-%d}",
                    "tone": "good" if stats["period_return"] >= 0 else "bad",
                },
                {
                    "label": "CAGR (period)",
                    "value": pct(stats["cagr"]) if stats.get("cagr") is not None else "—",
                    "help": "Annualized over selected window",
                    "tone": "good" if (stats.get("cagr") or 0) > 0.1 else "neutral",
                },
                {
                    "label": "Max drawdown",
                    "value": pct(stats["max_drawdown"]),
                    "help": "Worst peak-to-trough in window",
                    "tone": "bad" if stats["max_drawdown"] < -0.2 else "warn",
                },
            ],
            cols=4,
        )

    # Title + meta live in Streamlit (outside Plotly) so legend never overlaps text
    st.markdown(f"**NAV history · {scheme_name}**")
    nav_fig = nav_history_chart(
        nav_view,
        title=f"NAV · {scheme_name}",
        show_ma=show_ma,
        ma_window=50 if len(nav_view) > 120 else 20,
        normalize=normalize,
        source=source,
        height=460,
    )
    cap = nav_history_caption(nav_fig)
    if cap:
        st.caption(cap)
    st.plotly_chart(nav_fig, use_container_width=True)

    if show_dd and len(nav_view) > 5:
        st.plotly_chart(
            drawdown_chart(nav_view, title="Drawdown from peak"),
            use_container_width=True,
        )

    with st.expander("NAV data table (last 30 points)"):
        tail = nav_view.tail(30).rename("NAV").reset_index()
        tail.columns = ["Date", "NAV"]
        st.dataframe(tail, use_container_width=True, hide_index=True)
else:
    st.info("Click **Fetch real NAV history** to load and chart historical NAVs for this scheme.")

# Holdings preview if cached
hold_bundle = st.session_state["holdings_viz_cache"].get(code)
if hold_bundle and hold_bundle.get("df") is not None:
    st.markdown("---")
    st.subheader("Holdings preview")
    st.caption(f"Source: `{hold_bundle.get('source')}`")
    live, matched = get_market_client().enrich_holdings(hold_bundle["df"].head(25))
    if matched:
        st.caption(f"Live BSE quotes matched for {matched} of the top holdings.")
        st.dataframe(live, use_container_width=True, hide_index=True)
    else:
        st.dataframe(hold_bundle["df"].head(25), use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Module 2: portfolio turnover + dividend history
# ---------------------------------------------------------------------------
st.markdown("---")
st.subheader("Costs & distributions")

tcol1, tcol2 = st.columns(2)
try:
    enriched_meta = svc.get_enriched_meta(code, scheme_name)
except Exception:
    enriched_meta = {}

turnover = enriched_meta.get("portfolio_turnover")
tcol1.metric(
    "Portfolio turnover",
    f"{float(turnover):.0f}%" if turnover is not None else "—",
    help=(
        "Share of the book traded over a year. High turnover means transaction "
        "costs the TER does not show."
    ),
)
tcol2.metric(
    "Expense ratio",
    f"{float(enriched_meta['expense_ratio']):.2f}%"
    if enriched_meta.get("expense_ratio") is not None
    else "—",
)

if st.button("Load dividend / IDCW history"):
    with st.spinner("Resolving distributions…"):
        try:
            rows, note = svc.get_dividends(code, scheme_name)
            st.session_state.setdefault("div_cache", {})[code] = (rows, note)
        except Exception as exc:
            st.error(f"Could not load distributions: {exc}")

div_bundle = st.session_state.get("div_cache", {}).get(code)
if div_bundle:
    rows, note = div_bundle
    if rows:
        # A derived figure is an estimate; saying so is not optional.
        if any(r.get("source") == "derived" for r in rows):
            st.warning(
                "These distributions are **estimated** from NAV divergence against "
                "the Growth plan, not reported by the provider. Treat them as "
                "indicative."
            )
        st.caption(note)
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info(note)
