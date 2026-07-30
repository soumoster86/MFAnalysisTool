"""Dark theme and Plotly defaults for the Streamlit UI.

Selectors target `data-testid` attributes rather than emotion class names or
`data-baseweb`. Streamlit regenerates emotion classes on every build and has
dropped `data-baseweb` entirely, which had quietly killed the tab and expander
rules here; `data-testid` is the contract it actually keeps stable.

The accent is green throughout, matching `primaryColor` in
`.streamlit/config.toml` (which drives Streamlit's own sliders, checkboxes and
focus rings) and the report branding. Previously the custom CSS painted buttons
and tabs blue while Streamlit painted its widgets green, so the two halves of
the same screen disagreed.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on path when Streamlit loads pages in isolation
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# --------------------------------------------------------------------------
# Palette — one definition, exported to CSS variables and to Plotly.
# --------------------------------------------------------------------------
BG_DEEP = "#0b0e11"
BG = "#0f1318"
SURFACE = "#151a21"
SURFACE_2 = "#1b212b"
BORDER = "#243041"
BORDER_SOFT = "#1e2630"

TEXT = "#e6edf3"
TEXT_DIM = "#9aa9bd"
TEXT_FAINT = "#6b7b90"

ACCENT = "#22c55e"
ACCENT_DIM = "#16a34a"
ACCENT_SOFT = "rgba(34,197,94,0.12)"

POSITIVE = "#3fb950"
NEGATIVE = "#f85149"
CAUTION = "#d29922"
INFO = "#58a6ff"

# Categorical series for charts. Accent first so a single-series chart picks up
# the brand colour, then hues chosen to stay distinguishable on a dark ground.
SERIES = [
    "#22c55e",
    "#58a6ff",
    "#d2a8ff",
    "#ffa657",
    "#f778ba",
    "#56d4dd",
    "#f85149",
    "#a5d6a7",
    "#7c8fff",
    "#e3b341",
    "#79c0ff",
    "#ff9492",
]

FONT_SANS = "'IBM Plex Sans', system-ui, -apple-system, 'Segoe UI', sans-serif"
FONT_MONO = "'IBM Plex Mono', 'SF Mono', Consolas, monospace"


CUSTOM_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

:root {{
  --bg-deep: {BG_DEEP};
  --bg: {BG};
  --surface: {SURFACE};
  --surface-2: {SURFACE_2};
  --border: {BORDER};
  --border-soft: {BORDER_SOFT};
  --text: {TEXT};
  --text-dim: {TEXT_DIM};
  --text-faint: {TEXT_FAINT};
  --accent: {ACCENT};
  --accent-dim: {ACCENT_DIM};
  --accent-soft: {ACCENT_SOFT};
  --positive: {POSITIVE};
  --negative: {NEGATIVE};
  --caution: {CAUTION};
  --font-sans: {FONT_SANS};
  --font-mono: {FONT_MONO};
  --radius: 10px;
}}

html, body, [class*="css"] {{ font-family: var(--font-sans); }}

.stApp {{
  background:
    radial-gradient(1200px 600px at 15% -10%, rgba(34,197,94,0.06), transparent 60%),
    linear-gradient(180deg, var(--bg-deep) 0%, #12161c 45%, var(--bg) 100%);
  color: var(--text);
}}

/* Trim Streamlit's default top padding — the page title sat too low. */
.block-container {{ padding-top: 2.4rem; padding-bottom: 3rem; }}

/* ---------------------------------------------------------------- sidebar */
section[data-testid="stSidebar"] {{
  background: #0a0d10;
  border-right: 1px solid var(--border-soft);
}}
section[data-testid="stSidebar"] * {{ color: #c9d1d9; }}
[data-testid="stSidebarNavLink"] {{
  border-radius: 8px;
  transition: background 0.12s ease;
}}
[data-testid="stSidebarNavLink"]:hover {{ background: rgba(255,255,255,0.04); }}
[data-testid="stSidebarNavLink"][aria-current="page"] {{
  background: var(--accent-soft);
  box-shadow: inset 2px 0 0 var(--accent);
}}
[data-testid="stSidebarNavLink"][aria-current="page"] span {{
  color: var(--accent) !important;
  font-weight: 600;
}}

/* ------------------------------------------------------------- typography */
h1, h2, h3 {{
  color: #f0f3f6 !important;
  letter-spacing: -0.02em;
  font-weight: 600 !important;
}}
h1 {{ font-size: 1.9rem !important; }}
h2 {{ font-size: 1.32rem !important; margin-top: 0.4rem !important; }}
h3 {{ font-size: 1.08rem !important; }}
a {{ color: var(--accent) !important; }}

/* ------------------------------------------------------------------ cards */
[data-testid="stMetric"] {{
  background: linear-gradient(180deg, var(--surface) 0%, #12171e 100%);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 16px;
  box-shadow: 0 2px 10px rgba(0,0,0,0.28);
  transition: border-color 0.15s ease, transform 0.15s ease;
}}
[data-testid="stMetric"]:hover {{
  border-color: #334358;
  transform: translateY(-1px);
}}
[data-testid="stMetricLabel"] {{
  color: var(--text-faint) !important;
  font-size: 0.72rem !important;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  font-weight: 600;
}}
[data-testid="stMetricValue"] {{
  color: #eef4fb !important;
  font-family: var(--font-mono);
  font-size: 1.45rem !important;
  font-weight: 600;
  letter-spacing: -0.01em;
}}
[data-testid="stMetricDelta"] {{ font-size: 0.8rem !important; font-weight: 600; }}

/* ---------------------------------------------------------------- buttons */
/* Tooltip-wrapped buttons sit outside .stButton, so target the testid. */
[data-testid^="stBaseButton"] {{
  border-radius: 8px !important;
  font-weight: 600 !important;
  transition: filter 0.14s ease, box-shadow 0.14s ease, border-color 0.14s ease;
}}
[data-testid="stBaseButton-primary"] {{
  background: linear-gradient(135deg, var(--accent) 0%, var(--accent-dim) 100%) !important;
  border: none !important;
  color: #06210f !important;
}}
[data-testid="stBaseButton-primary"]:hover {{
  filter: brightness(1.08);
  box-shadow: 0 0 0 3px var(--accent-soft);
}}
[data-testid="stBaseButton-secondary"] {{
  background: var(--surface) !important;
  border: 1px solid var(--border) !important;
  color: var(--text) !important;
}}
[data-testid="stBaseButton-secondary"]:hover {{
  border-color: var(--accent) !important;
  color: var(--accent) !important;
}}
[data-testid="stDownloadButton"] button {{
  border-radius: 8px !important;
  font-weight: 600 !important;
}}

/* ------------------------------------------------------------------- tabs */
[data-testid="stTabs"] [role="tablist"] {{
  gap: 4px;
  border-bottom: 1px solid var(--border);
}}
[data-testid="stTab"] {{
  color: var(--text-dim);
  border-radius: 8px 8px 0 0;
  padding: 0.45rem 0.9rem;
  transition: color 0.12s ease, background 0.12s ease;
}}
[data-testid="stTab"]:hover {{ color: var(--text); background: rgba(255,255,255,0.03); }}
[data-testid="stTab"][aria-selected="true"] {{
  color: var(--accent) !important;
  background: var(--accent-soft);
  box-shadow: inset 0 -2px 0 var(--accent);
}}

/* -------------------------------------------------------------- expanders */
[data-testid="stExpander"] {{
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: rgba(21,26,33,0.55);
  overflow: hidden;
}}
[data-testid="stExpander"] summary {{
  font-weight: 600;
  color: var(--text) !important;
  padding: 0.5rem 0.85rem;
}}
[data-testid="stExpander"] summary:hover {{ color: var(--accent) !important; }}

/* --------------------------------------------------------------- surfaces */
[data-testid="stDataFrame"], [data-testid="stTable"] {{
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  font-size: 0.88rem;
}}
[data-testid="stTable"] thead tr th {{
  background: var(--surface-2) !important;
  color: var(--text-dim) !important;
  font-weight: 600;
  text-transform: uppercase;
  font-size: 0.72rem;
  letter-spacing: 0.05em;
}}
[data-testid="stPlotlyChart"] {{
  background: rgba(21,26,33,0.4);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius);
  padding: 4px;
}}

[data-testid="stAlert"] {{ border-radius: var(--radius); border-left-width: 3px; }}

/* ----------------------------------------------------------------- pieces */
.score-pill {{
  display: inline-block;
  padding: 4px 12px;
  border-radius: 999px;
  font-family: var(--font-mono);
  font-weight: 600;
  font-size: 0.95rem;
}}
.score-high {{ background: rgba(34,197,94,0.14); color: var(--positive); border: 1px solid #238636; }}
.score-mid  {{ background: rgba(210,153,34,0.14); color: var(--caution); border: 1px solid #9e6a03; }}
.score-low  {{ background: rgba(248,81,73,0.14); color: var(--negative); border: 1px solid #da3633; }}

/* Page header block */
.page-head {{
  display: flex;
  align-items: flex-start;
  gap: 0.85rem;
  padding: 0 0 0.55rem 0;
  border-bottom: 1px solid var(--border);
  margin-bottom: 1.1rem;
}}
.page-head .ph-icon {{
  font-size: 1.6rem;
  line-height: 1.9rem;
  filter: saturate(1.1);
}}
.page-head .ph-title {{
  margin: 0;
  font-size: 1.55rem;
  font-weight: 650;
  letter-spacing: -0.02em;
  color: #f0f3f6;
}}
.page-head .ph-sub {{
  margin: 0.15rem 0 0 0;
  color: var(--text-dim);
  font-size: 0.9rem;
  line-height: 1.35rem;
}}

.hero-banner {{
  background: linear-gradient(105deg, #0d1b2a 0%, #1b2838 50%, #0b1320 100%);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 1.25rem 1.5rem;
  margin-bottom: 1rem;
}}
.hero-banner h1 {{ margin: 0; font-size: 1.6rem; }}
.hero-banner p {{ margin: 0.35rem 0 0 0; color: var(--text-dim); font-size: 0.95rem; }}

.muted {{ color: var(--text-dim); font-size: 0.85rem; }}
.card {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1rem;
  margin-bottom: 0.75rem;
}}
.empty-state {{
  border: 1px dashed var(--border);
  border-radius: var(--radius);
  padding: 1.6rem 1.4rem;
  text-align: center;
  color: var(--text-dim);
  background: rgba(21,26,33,0.35);
}}
.empty-state .es-icon {{ font-size: 1.8rem; display: block; margin-bottom: 0.4rem; }}
.empty-state .es-title {{ color: var(--text); font-weight: 600; font-size: 1rem; }}

hr {{ border-color: var(--border) !important; }}
[data-testid="stCaptionContainer"] {{ color: var(--text-dim) !important; }}
</style>
"""

# --------------------------------------------------------------------------
# Plotly
# --------------------------------------------------------------------------
PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color=TEXT_DIM, family="IBM Plex Sans", size=12),
    title=dict(font=dict(color=TEXT, size=14), x=0, xanchor="left"),
    margin=dict(l=48, r=24, t=44, b=44),
    xaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER, linecolor=BORDER, ticks="outside",
               tickcolor=BORDER, tickfont=dict(size=11)),
    yaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER, linecolor=BORDER, ticks="outside",
               tickcolor=BORDER, tickfont=dict(size=11)),
    colorway=SERIES,
    legend=dict(
        bgcolor="rgba(0,0,0,0)",
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="left",
        x=0,
        font=dict(size=11),
    ),
    # One tooltip listing every series at the hovered x, instead of a separate
    # tooltip per trace — far easier to compare funds on a shared axis.
    hovermode="x unified",
    hoverlabel=dict(
        bgcolor=SURFACE_2,
        bordercolor=BORDER,
        font=dict(family="IBM Plex Sans", size=11, color=TEXT),
    ),
)

# Charts without a shared x axis (pies, treemaps, gauges, scatter) read better
# with the per-point tooltip.
_NON_CARTESIAN = {"pie", "treemap", "sunburst", "indicator", "scatterpolar", "heatmap"}


def apply_theme() -> None:
    import streamlit as st

    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def score_class(score: float) -> str:
    if score >= 70:
        return "score-high"
    if score >= 50:
        return "score-mid"
    return "score-low"


def score_colour(score: float) -> str:
    if score >= 70:
        return POSITIVE
    if score >= 50:
        return CAUTION
    return NEGATIVE


def style_fig(fig):
    """Apply the shared look. Merges, so per-chart settings survive."""
    layout = dict(PLOTLY_LAYOUT)

    kinds = {getattr(tr, "type", "") for tr in fig.data}
    if kinds & _NON_CARTESIAN or not kinds:
        # A unified x tooltip is meaningless without a shared x axis, and on a
        # pie it renders as an empty box.
        layout = {**layout, "hovermode": "closest"}
    fig.update_layout(**layout)
    return fig
