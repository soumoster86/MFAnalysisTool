"""Screener — rank the fund universe by health score."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

# Streamlit multipage pages may not inherit path setup — ensure project root
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st

from frontend.theme import apply_theme

apply_theme()

st.title("Screener")
st.caption(
    "Top funds by health score — per category and overall · "
    "Direct Growth plans · NAV-based scoring"
)

try:
    from services.screener.screener_service import (
        DEFAULT_MIN_YEARS,
        MIN_FUNDS_PER_CATEGORY,
        ScreenerService,
    )
except Exception as exc:
    st.error("Failed to import the screener backend.")
    st.code(f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")
    st.stop()


@st.cache_resource(show_spinner=False)
def _service() -> ScreenerService:
    return ScreenerService()


try:
    svc = _service()
except Exception as exc:
    st.error("Failed to create the screener service.")
    st.code(f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")
    st.stop()

# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------
f1, f2, f3 = st.columns([2, 1, 1])
with f1:
    try:
        cats = svc.categories()
    except Exception:
        cats = []
    pick_cat = st.selectbox("Score which category", ["All"] + cats)
with f2:
    batch = st.slider("Funds per run", 25, 400, 150, step=25)
with f3:
    min_years = st.slider(
        "Min history (years)",
        0.0,
        7.0,
        DEFAULT_MIN_YEARS,
        step=0.5,
        help=(
            "A fund with a few months of data can post a flattering annualised "
            "return off one good run. Three years is the conventional bar."
        ),
    )

b1, b2 = st.columns(2)
with b1:
    run_score = st.button("Score more funds", type="primary", use_container_width=True)
with b2:
    rescore = st.button("Re-score this category", use_container_width=True)

if run_score or rescore:
    progress = st.progress(0.0, text="Starting…")

    def _tick(pct: float, msg: str) -> None:
        progress.progress(min(1.0, max(0.0, pct)), text=msg)

    try:
        out = svc.score_universe(
            limit=batch,
            subcategory=None if pick_cat == "All" else pick_cat,
            rescore=rescore,
            progress=_tick,
        )
        progress.empty()
        parts = [f"Scored **{out.scored}**"]
        if out.skipped_short_history:
            parts.append(f"{out.skipped_short_history} skipped (history under a year)")
        if out.skipped_fabricated:
            parts.append(f"{out.skipped_fabricated} skipped (synthetic NAV)")
        if out.failed:
            parts.append(f"{out.failed} failed")
        st.success(" · ".join(parts) + f" in {out.elapsed_seconds:.0f}s")
        if out.errors:
            with st.expander("Scoring notes"):
                for e in out.errors:
                    st.caption(e)
    except Exception as exc:
        progress.empty()
        st.error("Scoring failed")
        st.code(f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")

# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------
try:
    cov = svc.coverage(min_years=min_years)
except Exception as exc:
    st.error(f"Could not read coverage: {exc}")
    st.stop()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Universe", f"{cov['universe']:,}", help="Direct Growth plans on AMFI")
c2.metric("Scored", f"{cov['scored']:,}")
c3.metric("Rankable", f"{cov['rankable']:,}", help="After history and data-quality filters")
c4.metric("Categories", cov["categories"])

if cov["scored"] == 0:
    st.info(
        "Nothing scored yet. Pick a category (or **All**) and press "
        "**Score more funds** — each run fetches NAV history for that many funds."
    )
    st.stop()

pct = cov["scored"] / cov["universe"] if cov["universe"] else 0
st.progress(min(1.0, pct), text=f"{pct:.0%} of the universe scored")

notes = []
if cov["excluded_fabricated"]:
    notes.append(
        f"**{cov['excluded_fabricated']}** excluded — scored on a synthetic NAV path. "
        "Ranking fabricated performance beside real performance would be worse "
        "than leaving them out."
    )
if cov["excluded_short_history"]:
    notes.append(
        f"**{cov['excluded_short_history']}** excluded — under {min_years:g} years of history."
    )
if notes:
    st.caption(" · ".join(notes))
if cov["last_scored_at"] is not None:
    st.caption(f"Last scored: {pd.to_datetime(cov['last_scored_at']):%Y-%m-%d %H:%M} UTC")

with st.expander("How this score is built"):
    st.markdown(
        """
The score is the same 0–100 `FundHealthScorer` blend used on the Fund Health
page: growth, risk, quality, cost efficiency, consistency and diversification,
from CAGR, alpha, beta, Sharpe, Sortino, drawdown, volatility, expense ratio
and AUM.

**One difference.** Screening thousands of funds skips the stock-level holdings
fetch, which is the slow call. The two holdings factors — top-10 concentration
and holdings count — are absent here and scored neutral, so a screener score
can sit a little away from the Fund Health page's score for the same fund. Open
a fund there for the full picture.

**Ranking across categories is not a like-for-like comparison.** The risk input
to the score is volatility, and volatility does not see credit risk. Credit
risk debt funds therefore look superb on a raw score — steady NAV, high Sharpe
— right up until a borrower defaults, which is exactly what happened to several
such funds in 2020. On the current data six of the raw top ten are credit risk
funds.

That is why **Peer-relative** is the default board: it ranks a fund by how far
it beats its *own* category, where every peer faces the same risks. Use raw
score only when you already know which category you want.
        """
    )

try:
    scores = svc.load_scores(min_years=min_years)
except Exception as exc:
    st.error("Could not load scores")
    st.code(f"{type(exc).__name__}: {exc}")
    st.stop()

if scores.empty:
    st.warning(
        f"No fund clears the {min_years:g}-year history filter yet. "
        "Lower it, or score more funds."
    )
    st.stop()

DISPLAY = {
    "overall_rank": "#",
    "category_percentile": "Peer %ile",
    "category_rank": "Cat #",
    "scheme_name": "Scheme",
    "amc": "AMC",
    "subcategory": "Category",
    "overall": "Score",
    "cagr": "CAGR",
    "volatility": "Vol",
    "sharpe": "Sharpe",
    "max_drawdown": "Max DD",
    "expense_ratio": "TER %",
    "years_covered": "Yrs",
}
FORMATS = {
    "CAGR": "{:.1%}",
    "Vol": "{:.1%}",
    "Max DD": "{:.1%}",
    "Sharpe": "{:.2f}",
    "Score": "{:.1f}",
    "TER %": "{:.2f}",
    "Yrs": "{:.1f}",
    "Peer %ile": "{:.0f}",
}


def _table(df: pd.DataFrame, cols: list[str]) -> None:
    view = df[[c for c in cols if c in df.columns]].rename(columns=DISPLAY)
    st.dataframe(
        view.style.format({k: v for k, v in FORMATS.items() if k in view.columns}, na_rep="—"),
        use_container_width=True,
        hide_index=True,
    )


tab_overall, tab_cats = st.tabs(["Overall ranking", "Top 10 by category"])

with tab_overall:
    st.subheader("Best funds across the scored universe")
    o1, o2 = st.columns([1, 1])
    with o1:
        mode = st.radio(
            "Rank by",
            ["Peer-relative (recommended)", "Raw score"],
            horizontal=True,
            help=(
                "Peer-relative ranks each fund against its own category, which "
                "is the only comparison that holds across categories."
            ),
        )
    with o2:
        how_many = st.slider("Show top", 10, 200, 50, step=10, key="overall_n")

    peer_relative = mode.startswith("Peer")
    if peer_relative:
        st.caption(
            "Ranked by percentile within category. A fund at 100 leads its own "
            "peer group — funds from different categories are never compared "
            "on their raw scores."
        )
    else:
        st.warning(
            "Raw scores are not comparable across categories. Volatility does "
            "not capture credit risk, so credit risk debt funds dominate this "
            "board while carrying default risk the score cannot see."
        )

    board = svc.overall_ranking(how_many, scores=scores, peer_relative=peer_relative)
    _table(
        board,
        [
            "category_percentile" if peer_relative else "overall_rank",
            "category_rank",
            "scheme_name",
            "amc",
            "subcategory",
            "overall",
            "cagr",
            "volatility",
            "sharpe",
            "max_drawdown",
            "expense_ratio",
            "years_covered",
        ],
    )
    st.download_button(
        "Download ranking (CSV)",
        board.to_csv(index=False).encode("utf-8"),
        file_name="mf_overall_ranking.csv",
        mime="text/csv",
    )

with tab_cats:
    st.subheader("Top 10 in each category")
    st.caption(
        f"Categories with fewer than {MIN_FUNDS_PER_CATEGORY} scored funds are "
        "hidden — a league table of two is noise."
    )
    groups = svc.top_by_category(10, scores=scores)
    if not groups:
        st.info(
            "No category has enough scored funds yet. Run **Score more funds** "
            "on **All** to broaden coverage."
        )
    else:
        only = st.multiselect(
            "Filter categories", sorted(groups), default=[], placeholder="All categories"
        )
        for name, group in groups.items():
            if only and name not in only:
                continue
            st.markdown(f"**{name}** · {len(group)} shown")
            _table(
                group,
                [
                    "category_rank",
                    "scheme_name",
                    "amc",
                    "overall",
                    "cagr",
                    "volatility",
                    "sharpe",
                    "max_drawdown",
                    "expense_ratio",
                    "years_covered",
                ],
            )

st.caption(
    "Scores rank risk-adjusted history. They are not investment advice, and past "
    "performance does not predict future returns."
)
