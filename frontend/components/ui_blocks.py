"""Readable UI blocks — replace raw JSON dumps with tables, cards, charts."""

from __future__ import annotations

import re
from typing import Any, Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from frontend.theme import score_class, style_fig


# ---------------------------------------------------------------------------
# Naming helpers
# ---------------------------------------------------------------------------

_STRIP_PATTERNS = [
    r"\s*-\s*Direct\s*Plan.*$",
    r"\s*-\s*Direct\s*Growth.*$",
    r"\s*-\s*Growth\s*Option.*$",
    r"\s*-\s*Direct.*$",
    r"\s*-\s*Regular.*$",
    r"\s*-\s*Growth.*$",
    r"\s+Direct\s+Plan.*$",
    r"\s+Direct\s+Growth.*$",
]


def short_fund_name(name: str, max_len: int = 28) -> str:
    """Compress long AMFI scheme names for charts/tables."""
    if not name:
        return "—"
    s = str(name).strip()
    for pat in _STRIP_PATTERNS:
        s2 = re.sub(pat, "", s, flags=re.I).strip()
        if len(s2) >= 8:
            s = s2
    s = re.sub(r"\s+", " ", s)
    if len(s) > max_len:
        return s[: max_len - 1].rstrip() + "…"
    return s


def short_labels(names: list[str], max_len: int = 22) -> list[str]:
    """Short names with uniqueness (Plotly/narwhals reject duplicate axis labels)."""
    labels = [short_fund_name(n, max_len) for n in names]
    seen: dict[str, int] = {}
    out: list[str] = []
    for lab in labels:
        if lab not in seen:
            seen[lab] = 0
            out.append(lab)
        else:
            seen[lab] += 1
            # Keep within max_len: "Aditya Birla~2"
            suffix = f"~{seen[lab]}"
            base = lab[: max(1, max_len - len(suffix))].rstrip("…").rstrip()
            out.append(f"{base}{suffix}")
    # Final pass if still collisions
    final_seen: set[str] = set()
    final: list[str] = []
    for i, lab in enumerate(out):
        if lab not in final_seen:
            final_seen.add(lab)
            final.append(lab)
        else:
            alt = f"F{i+1}"
            final_seen.add(alt)
            final.append(alt)
    return final


def unique_short_map(names: list[str], max_len: int = 18) -> dict[str, str]:
    """Map original names → unique short labels (stable for matrix axes)."""
    uniq = list(dict.fromkeys(str(n) for n in names))
    shorts = short_labels(uniq, max_len=max_len)
    return dict(zip(uniq, shorts))


# ---------------------------------------------------------------------------
# Cards / callouts
# ---------------------------------------------------------------------------

def insight_cards(items: list[dict[str, Any]], cols: int = 3) -> None:
    """
    items: [{label, value, help?, tone?}] tone in good|warn|bad|neutral
    """
    if not items:
        return
    n = min(cols, len(items))
    columns = st.columns(n)
    tone_border = {
        "good": "#238636",
        "warn": "#9e6a03",
        "bad": "#da3633",
        "neutral": "#243041",
    }
    for i, item in enumerate(items):
        with columns[i % n]:
            tone = item.get("tone", "neutral")
            border = tone_border.get(tone, tone_border["neutral"])
            help_txt = item.get("help") or ""
            st.markdown(
                f"""
                <div style="background:#151a21;border:1px solid {border};border-radius:10px;
                            padding:12px 14px;margin-bottom:8px;min-height:88px;">
                  <div style="color:#8b9bb4;font-size:0.72rem;text-transform:uppercase;
                              letter-spacing:0.04em;">{item.get('label','')}</div>
                  <div style="color:#e8eef7;font-family:'IBM Plex Mono',monospace;
                              font-size:1.35rem;font-weight:600;margin-top:4px;">
                    {item.get('value','—')}
                  </div>
                  <div style="color:#8b9bb4;font-size:0.78rem;margin-top:4px;">{help_txt}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def tip_list(tips: list[str], title: str = "Insights") -> None:
    if not tips:
        return
    st.markdown(f"**{title}**")
    for t in tips:
        level = "🟢"
        low = t.lower()
        if "high" in low or "concentration" in low or "breach" in low or "risk" in low:
            level = "🟠"
        if "severe" in low or "critical" in low or "weak" in low:
            level = "🔴"
        st.markdown(f"{level} {t}")


def kv_table(data: dict[str, Any], title: Optional[str] = None, value_fmt: str = "auto") -> None:
    """Render a key-value dict as a clean two-column table."""
    if title:
        st.markdown(f"**{title}**")
    if not data:
        st.caption("No data")
        return
    rows = []
    for k, v in data.items():
        key = str(k).replace("_", " ").title()
        if isinstance(v, float):
            if value_fmt == "pct" or (abs(v) <= 1 and "pct" not in str(k).lower() and "score" not in str(k).lower()):
                # heuristic: small floats that look like ratios
                if "score" in str(k).lower() or "ratio" in str(k).lower() or abs(v) > 1:
                    val = f"{v:.2f}"
                elif "overlap" in str(k).lower() or str(k).endswith("_pct") or "allocation" in str(k).lower():
                    val = f"{v:.1f}%" if abs(v) > 1 else f"{v * 100:.1f}%"
                else:
                    val = f"{v:.4f}" if abs(v) < 0.01 else f"{v:.2f}"
            else:
                val = f"{v:.2f}"
        elif v is None:
            val = "—"
        else:
            val = str(v)
        rows.append({"Metric": key, "Value": val})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def horizontal_bar(
    data: dict[str, float],
    title: str = "",
    x_title: str = "%",
    color: str = "#58a6ff",
    height: Optional[int] = None,
) -> go.Figure:
    if not data:
        fig = go.Figure()
        fig.update_layout(title=title, annotations=[dict(text="No data", showarrow=False)])
        return style_fig(fig)
    items = sorted(data.items(), key=lambda x: x[1])
    raw_names = [str(k) for k, _ in items]
    labels = short_labels(raw_names, max_len=36)
    values = [float(v) for _, v in items]
    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker=dict(color=color, line=dict(width=0)),
            text=[f"{v:.1f}%" if abs(v) <= 1000 else f"{v:,.0f}" for v in values],
            textposition="outside",
            cliponaxis=False,
        )
    )
    h = height or max(280, 28 * len(labels) + 80)
    fig.update_layout(
        title=title,
        xaxis_title=x_title,
        yaxis_title="",
        height=h,
        margin=dict(l=10, r=40, t=40, b=30),
    )
    return style_fig(fig)


def pairwise_overlap_heatmap(
    pairwise: dict[str, float],
    title: str = "Fund overlap heatmap (%)",
) -> go.Figure:
    """
    pairwise keys look like "Long Fund A ∩ Long Fund B" or "A × B".
    Builds a symmetric matrix with short labels.
    """
    if not pairwise:
        fig = go.Figure()
        fig.update_layout(title=title, annotations=[dict(text="Need 2+ funds", showarrow=False)])
        return style_fig(fig)

    pairs: list[tuple[str, str, float]] = []
    names: set[str] = set()
    for key, val in pairwise.items():
        parts = re.split(r"\s*[∩×xX]\s*", str(key), maxsplit=1)
        if len(parts) != 2:
            # fallback split on " vs "
            parts = re.split(r"\s+vs\s+", str(key), maxsplit=1, flags=re.I)
        if len(parts) != 2:
            continue
        a, b = parts[0].strip(), parts[1].strip()
        v = float(val)
        # Overlap % is [0, 100]; clamp bad upstream values
        v = max(0.0, min(100.0, v))
        pairs.append((a, b, v))
        names.add(a)
        names.add(b)

    if not names:
        fig = go.Figure()
        fig.update_layout(title=title)
        return style_fig(fig)

    ordered = sorted(names)
    short = unique_short_map(ordered, max_len=20)

    n = len(ordered)
    mat = [[0.0] * n for _ in range(n)]
    idx = {name: i for i, name in enumerate(ordered)}
    for a, b, v in pairs:
        i, j = idx[a], idx[b]
        mat[i][j] = v
        mat[j][i] = v
    for i in range(n):
        mat[i][i] = 100.0  # self-overlap

    labels = [short[n] for n in ordered]
    fig = go.Figure(
        data=go.Heatmap(
            z=mat,
            x=labels,
            y=labels,
            colorscale=[
                [0.0, "#0d1b2a"],
                [0.2, "#1b4332"],
                [0.4, "#40916c"],
                [0.6, "#d4a72c"],
                [0.8, "#e85d04"],
                [1.0, "#9b2226"],
            ],
            zmin=0,
            zmax=100,
            text=[[f"{v:.0f}" if i != j else "—" for j, v in enumerate(row)] for i, row in enumerate(mat)],
            texttemplate="%{text}",
            textfont=dict(size=11, color="#e6edf3"),
            hovertemplate="%{y} × %{x}<br>Overlap: %{z:.1f}%<extra></extra>",
            colorbar=dict(title="Overlap %"),
        )
    )
    fig.update_layout(
        title=title,
        height=max(360, 40 * n + 120),
        xaxis=dict(tickangle=-35, side="bottom"),
        yaxis=dict(autorange="reversed"),
        margin=dict(l=20, r=20, t=50, b=80),
    )
    return style_fig(fig)


def pairwise_overlap_table(pairwise: dict[str, float]) -> pd.DataFrame:
    rows = []
    for key, val in pairwise.items():
        parts = re.split(r"\s*[∩×xX]\s*", str(key), maxsplit=1)
        if len(parts) != 2:
            parts = [str(key), ""]
        a, b = parts[0].strip(), parts[1].strip()
        v = float(val)
        v = max(0.0, min(100.0, v))
        if v >= 40:
            level = "High"
        elif v >= 20:
            level = "Medium"
        else:
            level = "Low"
        rows.append(
            {
                "Fund A": short_fund_name(a, 34),
                "Fund B": short_fund_name(b, 34),
                "Overlap %": round(v, 1),
                "Level": level,
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Overlap %", ascending=False).reset_index(drop=True)
    return df


def top_holdings_bar(
    holdings: list[dict[str, Any]] | pd.DataFrame,
    title: str = "Top holdings",
    name_key: str = "security",
    weight_key: str = "weight_pct",
    top_n: int = 12,
) -> go.Figure:
    if isinstance(holdings, list):
        df = pd.DataFrame(holdings)
    else:
        df = holdings.copy()
    if df is None or df.empty:
        fig = go.Figure()
        fig.update_layout(title=title)
        return style_fig(fig)
    # flexible columns
    for nk in (name_key, "security_name", "name", "stock"):
        if nk in df.columns:
            name_key = nk
            break
    for wk in (weight_key, "weight", "pct", "allocation"):
        if wk in df.columns:
            weight_key = wk
            break
    if name_key not in df.columns or weight_key not in df.columns:
        fig = go.Figure()
        return style_fig(fig)
    df = df.nlargest(top_n, weight_key)
    data = {str(r[name_key]): float(r[weight_key]) for _, r in df.iterrows()}
    return horizontal_bar(data, title=title, x_title="Weight %", color="#79c0ff")


def allocation_donut(alloc: dict, title: str = "Allocation") -> go.Figure:
    if not alloc:
        fig = go.Figure()
        fig.update_layout(title=title, annotations=[dict(text="No data", showarrow=False)])
        return style_fig(fig)
    labels = [short_fund_name(str(k), 30) for k in alloc.keys()]
    values = list(alloc.values())
    fig = go.Figure(
        data=[
            go.Pie(
                labels=labels,
                values=values,
                hole=0.52,
                textinfo="label+percent",
                textposition="outside",
                insidetextorientation="radial",
                marker=dict(line=dict(color="#0b0e11", width=1)),
            )
        ]
    )
    fig.update_layout(
        title=title,
        showlegend=True,
        legend=dict(orientation="h", y=-0.08),
        margin=dict(l=10, r=10, t=40, b=10),
        height=380,
    )
    return style_fig(fig)


def weights_bar(weights: dict[str, float], title: str = "Allocation weights") -> go.Figure:
    """Weights as 0–1 or percent — normalizes for display as %."""
    if not weights:
        fig = go.Figure()
        return style_fig(fig)
    data = {}
    for k, v in weights.items():
        fv = float(v)
        data[short_fund_name(k, 32)] = fv * 100 if fv <= 1.0 else fv
    return horizontal_bar(data, title=title, x_title="Weight %", color="#3fb950")


def score_pill(score: float, label: str = "Score") -> None:
    st.markdown(
        f"**{label}** &nbsp; <span class='score-pill {score_class(score)}'>{score:.0f}/100</span>",
        unsafe_allow_html=True,
    )


def overlap_level_tone(pct: float) -> str:
    if pct >= 40:
        return "bad"
    if pct >= 20:
        return "warn"
    return "good"


def diversification_tone(score: float) -> str:
    if score >= 70:
        return "good"
    if score >= 50:
        return "warn"
    return "bad"


def risk_return_ranking_table(df: pd.DataFrame) -> pd.DataFrame:
    """Plain-language ranking table companion for the risk–return chart."""
    if df is None or df.empty:
        return pd.DataFrame()
    plot = df.dropna(subset=["volatility", "cagr"]).copy()
    if plot.empty:
        return plot

    rows = []
    for _, r in plot.iterrows():
        vol = float(r["volatility"])
        cagr = float(r["cagr"])
        sharpe = float(r["sharpe"]) if pd.notna(r.get("sharpe")) else None
        efficiency = cagr / vol if vol > 0 else None
        if sharpe is not None and sharpe >= 1.0:
            verdict = "Strong risk-adjusted"
        elif sharpe is not None and sharpe >= 0.6:
            verdict = "Balanced"
        elif cagr >= plot["cagr"].median() and vol <= plot["volatility"].median():
            verdict = "Attractive (return vs risk)"
        elif vol > plot["volatility"].median() and cagr < plot["cagr"].median():
            verdict = "Higher risk, lower return"
        else:
            verdict = "Mixed"
        rows.append(
            {
                "Fund": short_fund_name(str(r.get("name") or ""), 36),
                "Return (CAGR)": round(cagr * 100, 1),
                "Risk (Vol %)": round(vol * 100, 1),
                "Sharpe": round(sharpe, 2) if sharpe is not None else None,
                "Return / Risk": round(efficiency, 2) if efficiency is not None else None,
                "Reading": verdict,
            }
        )
    out = pd.DataFrame(rows)
    if "Sharpe" in out.columns and not out.empty:
        out = out.sort_values("Sharpe", ascending=False, na_position="last")
    return out.reset_index(drop=True)
