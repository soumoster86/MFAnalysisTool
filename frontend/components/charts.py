"""Reusable Plotly charts for the Streamlit UI."""

from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from frontend.theme import style_fig


def line_nav(nav: pd.Series, title: str = "NAV") -> go.Figure:
    df = nav.reset_index()
    df.columns = ["Date", "NAV"]
    fig = px.line(df, x="Date", y="NAV", title=title)
    return style_fig(fig)


def drawdown_chart(nav: pd.Series, title: str = "Drawdown") -> go.Figure:
    s = nav.dropna().astype(float)
    peak = s.cummax()
    dd = (s - peak) / peak
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=dd.index,
            y=dd.values,
            fill="tozeroy",
            name="Drawdown",
            line=dict(color="#f85149"),
        )
    )
    fig.update_layout(title=title, yaxis_tickformat=".0%")
    return style_fig(fig)


def allocation_pie(alloc: dict, title: str = "Allocation") -> go.Figure:
    if not alloc:
        fig = go.Figure()
        fig.update_layout(title=title, annotations=[dict(text="No data", showarrow=False)])
        return style_fig(fig)
    fig = px.pie(
        names=list(alloc.keys()),
        values=list(alloc.values()),
        title=title,
        hole=0.45,
    )
    return style_fig(fig)


def treemap_alloc(alloc: dict, title: str = "Allocation Treemap") -> go.Figure:
    if not alloc:
        fig = go.Figure()
        return style_fig(fig)
    fig = px.treemap(
        names=list(alloc.keys()),
        parents=[""] * len(alloc),
        values=list(alloc.values()),
        title=title,
    )
    return style_fig(fig)


def correlation_heatmap(corr: pd.DataFrame, title: str = "Correlation") -> go.Figure:
    """Correlation matrix heatmap with unique axis labels (required by Plotly/narwhals)."""
    df = corr.copy()
    if not isinstance(df, pd.DataFrame) or df.empty:
        fig = go.Figure()
        fig.update_layout(title=title, annotations=[dict(text="No correlation data", showarrow=False)])
        return style_fig(fig)

    # Align index/columns and force unique string labels
    from frontend.components.ui_blocks import unique_short_map

    names = [str(c) for c in df.columns]
    # If index differs, include both for mapping consistency on shared names
    idx_names = [str(i) for i in df.index]
    label_map = unique_short_map(names + idx_names, max_len=20)
    df.index = pd.Index([label_map.get(str(i), str(i)) for i in df.index], dtype=object)
    df.columns = pd.Index([label_map.get(str(c), str(c)) for c in df.columns], dtype=object)

    # Drop accidental duplicate columns/rows (keep first)
    df = df.loc[:, ~df.columns.duplicated(keep="first")]
    df = df.loc[~df.index.duplicated(keep="first")]
    # Reindex to square if possible
    common = [c for c in df.columns if c in df.index]
    if common:
        df = df.loc[common, common]

    # Use go.Heatmap instead of px.imshow to avoid narwhals unique-name hard fail
    z = df.astype(float).values
    labels = list(df.columns.astype(str))
    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=labels,
            y=labels,
            colorscale="RdBu_r",
            zmin=-1,
            zmax=1,
            text=[[f"{v:.2f}" for v in row] for row in z],
            texttemplate="%{text}",
            textfont=dict(size=10),
            hovertemplate="%{y} vs %{x}<br>ρ = %{z:.2f}<extra></extra>",
            colorbar=dict(title="ρ"),
        )
    )
    fig.update_layout(
        title=title,
        xaxis=dict(tickangle=-35, side="bottom"),
        yaxis=dict(autorange="reversed"),
        height=max(360, 36 * len(labels) + 120),
        margin=dict(l=20, r=20, t=50, b=80),
    )
    return style_fig(fig)


def risk_return_scatter(
    df: pd.DataFrame,
    x: str = "volatility",
    y: str = "cagr",
    size: Optional[str] = None,
    hover: Optional[str] = "name",
    title: str = "Risk vs Return",
    label_col: Optional[str] = "name",
    color_col: Optional[str] = None,
    show_quadrants: bool = True,
    show_labels: bool = True,
) -> go.Figure:
    """
    Risk–return bubble chart designed for mutual-fund comparison.

    - X = risk (volatility), Y = return (CAGR)
    - Point size = Sharpe (or custom size column)
    - On-chart labels + rich hover
    - Quadrant guide: ideal is upper-left (higher return, lower risk)
    """
    if df is None or df.empty:
        fig = go.Figure()
        fig.update_layout(title=title, annotations=[dict(text="No data", showarrow=False)])
        return style_fig(fig)

    plot = df.copy().dropna(subset=[x, y])
    if plot.empty:
        fig = go.Figure()
        fig.update_layout(title=title)
        return style_fig(fig)

    from frontend.components.ui_blocks import short_fund_name, short_labels

    # Short unique labels for on-chart text
    raw_names = (
        plot[label_col].astype(str).tolist()
        if label_col and label_col in plot.columns
        else [f"Fund {i+1}" for i in range(len(plot))]
    )
    labels = short_labels(raw_names, max_len=22)
    plot = plot.reset_index(drop=True)
    plot["_label"] = labels
    plot["_full_name"] = raw_names

    # Bubble size from Sharpe (fallback equal size)
    if size and size in plot.columns:
        sizes = plot[size].fillna(0).astype(float).clip(lower=0)
        # Map to visible pixel range
        if sizes.max() > sizes.min():
            sizeref = 2.0 * sizes.max() / (48**2)
        else:
            sizeref = 0.02
        marker_size = sizes
    else:
        marker_size = pd.Series([1.0] * len(plot))
        sizeref = 2.0 / (36**2)

    # Distinct colors per fund
    palette = [
        "#58a6ff",
        "#3fb950",
        "#d2a8ff",
        "#ffa657",
        "#f85149",
        "#79c0ff",
        "#a5d6ff",
    ]
    colors = [palette[i % len(palette)] for i in range(len(plot))]

    # Hover text with plain language metrics
    hover_texts = []
    for _, row in plot.iterrows():
        bits = [f"<b>{row['_full_name']}</b>"]
        bits.append(f"Return (CAGR): {float(row[y])*100:.1f}%")
        bits.append(f"Risk (volatility): {float(row[x])*100:.1f}%")
        if "sharpe" in plot.columns and pd.notna(row.get("sharpe")):
            bits.append(f"Sharpe: {float(row['sharpe']):.2f}")
        if "health" in plot.columns and pd.notna(row.get("health")):
            bits.append(f"Health: {float(row['health']):.0f}/100")
        if "max_drawdown" in plot.columns and pd.notna(row.get("max_drawdown")):
            bits.append(f"Max drawdown: {float(row['max_drawdown'])*100:.1f}%")
        if "expense_ratio" in plot.columns and pd.notna(row.get("expense_ratio")):
            bits.append(f"Expense: {float(row['expense_ratio']):.2f}%")
        hover_texts.append("<br>".join(bits))

    fig = go.Figure()

    # Soft quadrant background using median as divider
    xs = plot[x].astype(float)
    ys = plot[y].astype(float)
    x_mid = float(xs.median())
    y_mid = float(ys.median())
    x_pad = max((xs.max() - xs.min()) * 0.18, 0.005)
    y_pad = max((ys.max() - ys.min()) * 0.18, 0.005)
    x0, x1 = float(xs.min() - x_pad), float(xs.max() + x_pad)
    y0, y1 = float(ys.min() - y_pad), float(ys.max() + y_pad)

    if show_quadrants and len(plot) >= 2:
        # Upper-left = better risk-adjusted zone highlight
        fig.add_shape(
            type="rect",
            x0=x0,
            x1=x_mid,
            y0=y_mid,
            y1=y1,
            fillcolor="rgba(63, 185, 80, 0.08)",
            line=dict(width=0),
            layer="below",
        )
        fig.add_shape(
            type="rect",
            x0=x_mid,
            x1=x1,
            y0=y0,
            y1=y_mid,
            fillcolor="rgba(248, 81, 73, 0.06)",
            line=dict(width=0),
            layer="below",
        )
        fig.add_hline(y=y_mid, line_dash="dot", line_color="#8b9bb4", line_width=1, opacity=0.6)
        fig.add_vline(x=x_mid, line_dash="dot", line_color="#8b9bb4", line_width=1, opacity=0.6)
        fig.add_annotation(
            x=x0 + (x_mid - x0) * 0.5,
            y=y1 - y_pad * 0.25,
            text="Better zone<br>(higher return, lower risk)",
            showarrow=False,
            font=dict(size=11, color="#3fb950"),
            opacity=0.9,
        )
        fig.add_annotation(
            x=x_mid + (x1 - x_mid) * 0.5,
            y=y0 + y_pad * 0.35,
            text="Weaker zone<br>(lower return, higher risk)",
            showarrow=False,
            font=dict(size=11, color="#f85149"),
            opacity=0.85,
        )

    # One trace per fund so legend is clear
    for i, row in plot.iterrows():
        fig.add_trace(
            go.Scatter(
                x=[float(row[x])],
                y=[float(row[y])],
                mode="markers+text" if show_labels else "markers",
                name=row["_label"],
                text=[row["_label"]] if show_labels else None,
                textposition="top center",
                textfont=dict(size=11, color="#e6edf3"),
                marker=dict(
                    size=float(marker_size.iloc[i]) if hasattr(marker_size, "iloc") else 18,
                    sizemode="area",
                    sizeref=sizeref,
                    sizemin=14,
                    color=colors[i],
                    line=dict(width=2, color="#e6edf3"),
                    opacity=0.92,
                ),
                hovertext=[hover_texts[i]],
                hoverinfo="text",
            )
        )

    fig.update_layout(
        title=dict(
            text=title
            + "<br><sup>Each bubble is a fund · farther right = more risk · higher = better return · larger bubble = better Sharpe</sup>",
            x=0,
            xanchor="left",
        ),
        xaxis=dict(
            title="Risk →  (annualized volatility)",
            tickformat=".0%",
            range=[x0, x1],
            zeroline=False,
            gridcolor="#243041",
        ),
        yaxis=dict(
            title="Return →  (CAGR)",
            tickformat=".0%",
            range=[y0, y1],
            zeroline=False,
            gridcolor="#243041",
        ),
        legend=dict(
            title="Funds",
            orientation="h",
            yanchor="bottom",
            y=-0.28,
            x=0,
            bgcolor="rgba(0,0,0,0)",
        ),
        height=520,
        margin=dict(l=60, r=30, t=80, b=100),
        hovermode="closest",
    )
    return style_fig(fig)


# risk_return_ranking_table lives in frontend.components.ui_blocks
# (imported by Fund Comparison page) to avoid Streamlit module-cache issues.


def efficient_frontier(points: list[dict], title: str = "Efficient Frontier") -> go.Figure:
    if not points:
        fig = go.Figure()
        fig.update_layout(title=title)
        return style_fig(fig)
    df = pd.DataFrame(points)
    fig = px.line(df, x="risk", y="return", markers=True, title=title)
    fig.update_layout(xaxis_title="Risk (σ)", yaxis_title="Expected Return")
    return style_fig(fig)


def gauge_score(score: float, title: str = "Health Score") -> go.Figure:
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=score,
            title={"text": title},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": "#58a6ff"},
                "steps": [
                    {"range": [0, 35], "color": "#3d1219"},
                    {"range": [35, 50], "color": "#3b2f0d"},
                    {"range": [50, 70], "color": "#1c2d3f"},
                    {"range": [70, 100], "color": "#0d3b2a"},
                ],
                "threshold": {
                    "line": {"color": "#f0f3f6", "width": 2},
                    "thickness": 0.75,
                    "value": score,
                },
            },
        )
    )
    return style_fig(fig)


def monte_carlo_hist(values: list[float], goal: Optional[float] = None, title: str = "Terminal Corpus") -> go.Figure:
    fig = px.histogram(x=values, nbins=40, title=title)
    if goal is not None:
        fig.add_vline(x=goal, line_dash="dash", line_color="#ffa657", annotation_text="Goal")
    return style_fig(fig)


def bar_scores(scores: dict, title: str = "Score Breakdown") -> go.Figure:
    fig = px.bar(
        x=list(scores.keys()),
        y=list(scores.values()),
        title=title,
        labels={"x": "Pillar", "y": "Score"},
    )
    fig.update_layout(yaxis_range=[0, 100])
    return style_fig(fig)


def sunburst_from_holdings(holdings: pd.DataFrame, title: str = "Holdings Sunburst") -> go.Figure:
    """
    Sector → security sunburst from fund holdings.

    Robust to Groww/CAS quirks: negative weights, null sectors, duplicates,
    and very wide books (caps leaf count so the browser stays responsive).
    """
    empty = go.Figure()
    empty.update_layout(
        title=title,
        annotations=[dict(text="No holdings data", showarrow=False, font=dict(color="#8b9bb4"))],
        height=420,
    )
    if holdings is None or (hasattr(holdings, "empty") and holdings.empty):
        return style_fig(empty)

    try:
        df = holdings.copy()
    except Exception:
        return style_fig(empty)

    # Flexible column names
    name_col = next(
        (c for c in ("security_name", "security", "name", "stock", "company_name") if c in df.columns),
        None,
    )
    weight_col = next(
        (c for c in ("weight_pct", "weight", "pct", "allocation", "corpus_per") if c in df.columns),
        None,
    )
    sector_col = next(
        (c for c in ("sector", "sector_name", "industry") if c in df.columns),
        None,
    )
    if not name_col or not weight_col:
        empty.update_layout(
            annotations=[dict(text="Holdings missing name/weight columns", showarrow=False)]
        )
        return style_fig(empty)

    work = pd.DataFrame(
        {
            "security": df[name_col].astype(str).str.strip().replace({"": "Unknown", "nan": "Unknown"}),
            "weight": pd.to_numeric(df[weight_col], errors="coerce"),
            "sector": (
                df[sector_col].astype(str).str.strip()
                if sector_col
                else pd.Series(["Unclassified"] * len(df))
            ),
        }
    )
    work["sector"] = work["sector"].replace(
        {"": "Unclassified", "nan": "Unclassified", "None": "Unclassified", "NaN": "Unclassified"}
    )
    # Plotly sunburst requires non-negative values
    work = work.dropna(subset=["weight"])
    work = work[work["weight"] > 0]
    if work.empty:
        empty.update_layout(
            annotations=[dict(text="No positive-weight holdings to chart", showarrow=False)]
        )
        return style_fig(empty)

    # Collapse duplicate security rows within a sector
    work = (
        work.groupby(["sector", "security"], as_index=False)["weight"]
        .sum()
        .sort_values("weight", ascending=False)
    )

    # Cap leaves for readability/performance; roll the rest into "Other"
    max_leaves = 40
    if len(work) > max_leaves:
        head = work.head(max_leaves).copy()
        tail_w = float(work.iloc[max_leaves:]["weight"].sum())
        if tail_w > 0:
            head = pd.concat(
                [
                    head,
                    pd.DataFrame(
                        [{"sector": "Other", "security": f"Other ({len(work) - max_leaves} names)", "weight": tail_w}]
                    ),
                ],
                ignore_index=True,
            )
        work = head

    try:
        # go.Sunburst is more reliable than px path= with Series quirks
        # Hierarchy: root → sector → security
        sectors = work.groupby("sector", as_index=False)["weight"].sum()
        labels: list[str] = ["Portfolio"]
        parents: list[str] = [""]
        values: list[float] = [float(work["weight"].sum())]
        ids: list[str] = ["root"]
        colors: list[str] = ["#1f6feb"]

        palette = [
            "#58a6ff",
            "#3fb950",
            "#d2a8ff",
            "#ffa657",
            "#f85149",
            "#79c0ff",
            "#a5d6ff",
            "#7ee787",
            "#ff7b72",
            "#d2a8ff",
        ]
        sector_color: dict[str, str] = {}
        for i, row in sectors.iterrows():
            sec = str(row["sector"])
            sid = f"sec::{sec}"
            sector_color[sec] = palette[i % len(palette)]
            labels.append(sec if len(sec) <= 28 else sec[:27] + "…")
            parents.append("root")
            values.append(float(row["weight"]))
            ids.append(sid)
            colors.append(sector_color[sec])

        for _, row in work.iterrows():
            sec = str(row["sector"])
            name = str(row["security"])
            label = name if len(name) <= 32 else name[:31] + "…"
            labels.append(label)
            parents.append(f"sec::{sec}")
            values.append(float(row["weight"]))
            ids.append(f"sec::{sec}::name::{name}")
            colors.append(sector_color.get(sec, "#58a6ff"))

        fig = go.Figure(
            go.Sunburst(
                ids=ids,
                labels=labels,
                parents=parents,
                values=values,
                branchvalues="total",
                marker=dict(colors=colors, line=dict(color="#0b0e11", width=1)),
                hovertemplate="<b>%{label}</b><br>Weight: %{value:.2f}%<br>%{percentParent:.1%} of parent<extra></extra>",
                maxdepth=3,
            )
        )
        fig.update_layout(
            title=title,
            height=480,
            margin=dict(l=10, r=10, t=50, b=10),
        )
        return style_fig(fig)
    except Exception as exc:
        # Fallback: simple sector treemap if sunburst fails
        try:
            sector_w = work.groupby("sector")["weight"].sum().reset_index()
            fig = px.treemap(
                sector_w,
                path=["sector"],
                values="weight",
                title=f"{title} (sector treemap fallback)",
            )
            fig.update_layout(height=420, margin=dict(l=10, r=10, t=50, b=10))
            return style_fig(fig)
        except Exception:
            empty.update_layout(
                annotations=[
                    dict(
                        text=f"Could not render holdings chart<br>{type(exc).__name__}",
                        showarrow=False,
                        font=dict(color="#f85149"),
                    )
                ]
            )
            return style_fig(empty)
