"""Bloomberg / TradingView inspired dark theme for Streamlit."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on path when Streamlit loads pages in isolation
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');

html, body, [class*="css"] {
  font-family: 'IBM Plex Sans', system-ui, sans-serif;
}

.stApp {
  background: linear-gradient(180deg, #0b0e11 0%, #12161c 40%, #0f1318 100%);
  color: #e6edf3;
}

/* Sidebar */
section[data-testid="stSidebar"] {
  background: #0a0d10;
  border-right: 1px solid #1e2630;
}
section[data-testid="stSidebar"] * {
  color: #c9d1d9 !important;
}

h1, h2, h3 {
  color: #f0f3f6 !important;
  letter-spacing: -0.02em;
  font-weight: 600 !important;
}

/* Metric cards */
div[data-testid="stMetric"] {
  background: #151a21;
  border: 1px solid #243041;
  border-radius: 10px;
  padding: 12px 14px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.25);
}
div[data-testid="stMetric"] label {
  color: #8b9bb4 !important;
  font-size: 0.8rem !important;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
div[data-testid="stMetric"] [data-testid="stMetricValue"] {
  color: #e8eef7 !important;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 1.4rem !important;
}

/* Buttons */
.stButton > button {
  background: linear-gradient(135deg, #1f6feb, #1158c7);
  color: white;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  transition: all 0.15s ease;
}
.stButton > button:hover {
  filter: brightness(1.1);
  box-shadow: 0 0 0 1px #388bfd;
}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
  gap: 6px;
  background: transparent;
}
.stTabs [data-baseweb="tab"] {
  background: #151a21;
  border-radius: 8px 8px 0 0;
  color: #9fb0c7;
  border: 1px solid #243041;
}
.stTabs [aria-selected="true"] {
  background: #1c2330 !important;
  color: #58a6ff !important;
  border-bottom-color: #58a6ff !important;
}

/* Dataframes */
div[data-testid="stDataFrame"] {
  border: 1px solid #243041;
  border-radius: 8px;
  overflow: hidden;
}

/* Info / success boxes */
.stAlert {
  border-radius: 8px;
}

/* Score badge */
.score-pill {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 999px;
  font-family: 'IBM Plex Mono', monospace;
  font-weight: 600;
  font-size: 0.95rem;
}
.score-high { background: #0d3b2a; color: #3fb950; border: 1px solid #238636; }
.score-mid { background: #3b2f0d; color: #d4a72c; border: 1px solid #9e6a03; }
.score-low { background: #3d1219; color: #f85149; border: 1px solid #da3633; }

.hero-banner {
  background: linear-gradient(105deg, #0d1b2a 0%, #1b2838 50%, #0b1320 100%);
  border: 1px solid #243041;
  border-radius: 14px;
  padding: 1.25rem 1.5rem;
  margin-bottom: 1rem;
}
.hero-banner h1 {
  margin: 0;
  font-size: 1.6rem;
}
.hero-banner p {
  margin: 0.35rem 0 0 0;
  color: #8b9bb4;
  font-size: 0.95rem;
}
.muted { color: #8b9bb4; font-size: 0.85rem; }
.card {
  background: #151a21;
  border: 1px solid #243041;
  border-radius: 10px;
  padding: 1rem;
  margin-bottom: 0.75rem;
}
hr { border-color: #243041 !important; }

/* Dataframe readability on dark theme */
div[data-testid="stDataFrame"] {
  font-size: 0.9rem;
}
div[data-testid="stDataFrame"] thead tr th {
  background-color: #1c2330 !important;
  color: #c9d1d9 !important;
}

/* Expander */
.streamlit-expanderHeader {
  font-weight: 600;
  color: #e6edf3 !important;
}

/* Captions */
.stCaption, [data-testid="stCaptionContainer"] {
  color: #8b9bb4 !important;
}
</style>
"""

PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(21,26,33,0.9)",
    font=dict(color="#c9d1d9", family="IBM Plex Sans"),
    margin=dict(l=40, r=20, t=40, b=40),
    xaxis=dict(gridcolor="#243041", zerolinecolor="#243041"),
    yaxis=dict(gridcolor="#243041", zerolinecolor="#243041"),
    colorway=["#58a6ff", "#3fb950", "#d2a8ff", "#f78166", "#ffa657", "#79c0ff", "#ff7b72"],
    legend=dict(bgcolor="rgba(0,0,0,0)"),
)


def apply_theme() -> None:
    import streamlit as st

    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def score_class(score: float) -> str:
    if score >= 70:
        return "score-high"
    if score >= 50:
        return "score-mid"
    return "score-low"


def style_fig(fig):
    fig.update_layout(**PLOTLY_LAYOUT)
    return fig
