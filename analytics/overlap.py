"""Portfolio overlap and concentration analysis."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import pandas as pd


@dataclass
class OverlapResult:
    holding_overlap_pct: float = 0.0
    sector_overlap_pct: float = 0.0
    amc_concentration: dict[str, float] = field(default_factory=dict)
    category_concentration: dict[str, float] = field(default_factory=dict)
    top_repeated_stocks: list[dict[str, Any]] = field(default_factory=list)
    pairwise_overlap: dict[str, float] = field(default_factory=dict)
    diversification_score: float = 50.0
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PortfolioOverlapAnalyzer:
    """
    Analyze overlap across multiple funds' holdings.

    holdings_by_fund: {fund_name: DataFrame with columns
        [security_name, weight_pct, sector?, amc?, category?]}
    portfolio_weights: optional {fund_name: weight 0-1}
    """

    def analyze(
        self,
        holdings_by_fund: dict[str, pd.DataFrame],
        portfolio_weights: Optional[dict[str, float]] = None,
        fund_meta: Optional[dict[str, dict[str, Any]]] = None,
    ) -> OverlapResult:
        fund_meta = fund_meta or {}
        names = list(holdings_by_fund.keys())
        if not names:
            return OverlapResult(suggestions=["Add funds with holdings data to analyze overlap."])

        # Normalize weights
        if portfolio_weights is None:
            w = {n: 1.0 / len(names) for n in names}
        else:
            total = sum(portfolio_weights.get(n, 0) for n in names) or 1.0
            w = {n: portfolio_weights.get(n, 0) / total for n in names}

        # Effective portfolio stock weights
        stock_w: dict[str, float] = defaultdict(float)
        stock_fund_count: dict[str, set[str]] = defaultdict(set)
        sector_w: dict[str, float] = defaultdict(float)

        for fname, df in holdings_by_fund.items():
            if df is None or df.empty:
                continue
            col_sec = self._col(df, ["security_name", "name", "stock", "security"])
            col_wt = self._col(df, ["weight_pct", "weight", "pct", "allocation"])
            col_sector = self._col(df, ["sector", "industry"])
            if not col_sec or not col_wt:
                continue
            for _, row in df.iterrows():
                sec = str(row[col_sec]).strip()
                try:
                    wt_raw = abs(float(row[col_wt]))
                except (TypeError, ValueError):
                    continue
                wt = wt_raw / 100.0 if wt_raw > 1.5 else wt_raw
                if wt > 1.0:
                    continue  # skip non-weight columns mistaken as allocation
                stock_w[sec] += w[fname] * wt
                stock_fund_count[sec].add(fname)
                if col_sector and pd.notna(row.get(col_sector)):
                    sector_w[str(row[col_sector])] += w[fname] * wt

        # Pairwise holding overlap (min-weight sum of common holdings)
        pairwise: dict[str, float] = {}
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                pairwise[f"{a} × {b}"] = self._pairwise_overlap(
                    holdings_by_fund.get(a), holdings_by_fund.get(b)
                )

        avg_pair = sum(pairwise.values()) / len(pairwise) if pairwise else 0.0

        # Sector HHI-ish overlap proxy: sum of squared sector weights
        sector_hhi = sum(v ** 2 for v in sector_w.values())
        sector_overlap = min(100.0, sector_hhi * 100 * 2)  # scale for readability

        # AMC / category concentration from meta + weights
        amc_c: dict[str, float] = defaultdict(float)
        cat_c: dict[str, float] = defaultdict(float)
        for fname, wt in w.items():
            meta = fund_meta.get(fname, {})
            amc = meta.get("amc") or "Unknown"
            cat = meta.get("category") or "Unknown"
            amc_c[amc] += wt * 100
            cat_c[cat] += wt * 100

        repeated = [
            {
                "security": s,
                "funds": sorted(list(fs)),
                "fund_count": len(fs),
                "portfolio_weight_pct": round(stock_w[s] * 100, 2),
            }
            for s, fs in stock_fund_count.items()
            if len(fs) > 1
        ]
        repeated.sort(key=lambda x: (-x["fund_count"], -x["portfolio_weight_pct"]))

        top_weight = max(stock_w.values()) * 100 if stock_w else 0
        div_score = max(5.0, 100 - avg_pair * 0.6 - top_weight * 0.8 - max(amc_c.values(), default=0) * 0.2)

        suggestions = self._suggestions(avg_pair, amc_c, cat_c, repeated, top_weight)

        return OverlapResult(
            holding_overlap_pct=round(avg_pair, 2),
            sector_overlap_pct=round(sector_overlap, 2),
            amc_concentration={k: round(v, 2) for k, v in sorted(amc_c.items(), key=lambda x: -x[1])},
            category_concentration={k: round(v, 2) for k, v in sorted(cat_c.items(), key=lambda x: -x[1])},
            top_repeated_stocks=repeated[:15],
            pairwise_overlap={k: round(v, 2) for k, v in pairwise.items()},
            diversification_score=round(div_score, 1),
            suggestions=suggestions,
        )

    def _pairwise_overlap(
        self, df_a: Optional[pd.DataFrame], df_b: Optional[pd.DataFrame]
    ) -> float:
        if df_a is None or df_b is None or df_a.empty or df_b.empty:
            return 0.0
        col_a_s = self._col(df_a, ["security_name", "name", "stock", "security"])
        col_a_w = self._col(df_a, ["weight_pct", "weight", "pct", "allocation"])
        col_b_s = self._col(df_b, ["security_name", "name", "stock", "security"])
        col_b_w = self._col(df_b, ["weight_pct", "weight", "pct", "allocation"])
        if not all([col_a_s, col_a_w, col_b_s, col_b_w]):
            return 0.0

        def to_map(df, cs, cw):
            m: dict[str, float] = {}
            for _, row in df.iterrows():
                name = str(row[cs]).strip().upper()
                try:
                    wt = abs(float(row[cw]))
                except (TypeError, ValueError):
                    continue
                # weight_pct is usually 0–100; also accept 0–1 fractions
                if wt > 1.5:
                    wt = wt / 100.0
                # ignore junk rows (market-value mistaken as weight)
                if wt > 1.0:
                    continue
                m[name] = m.get(name, 0.0) + wt
            # renormalize if slightly over 1 due to rounding
            total = sum(m.values())
            if total > 1.05:
                m = {k: v / total for k, v in m.items()}
            return m

        ma, mb = to_map(df_a, col_a_s, col_a_w), to_map(df_b, col_b_s, col_b_w)
        common = set(ma) & set(mb)
        if not common:
            return 0.0
        # Portfolio overlap % ≈ sum of min weights of common holdings * 100
        overlap = sum(min(ma[s], mb[s]) for s in common) * 100.0
        return float(max(0.0, min(100.0, overlap)))

    @staticmethod
    def _col(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
        lower = {c.lower(): c for c in df.columns}
        for c in candidates:
            if c.lower() in lower:
                return lower[c.lower()]
        return None

    def _suggestions(
        self,
        avg_pair: float,
        amc_c: dict[str, float],
        cat_c: dict[str, float],
        repeated: list[dict],
        top_weight: float,
    ) -> list[str]:
        tips: list[str] = []
        if avg_pair > 40:
            tips.append(
                f"High average fund overlap ({avg_pair:.0f}%). Consider funds from different styles/categories."
            )
        if amc_c and max(amc_c.values()) > 50:
            top_amc = max(amc_c, key=amc_c.get)  # type: ignore[arg-type]
            tips.append(f"AMC concentration: {top_amc} is {amc_c[top_amc]:.0f}% of portfolio. Diversify AMC exposure.")
        if cat_c and max(cat_c.values()) > 70:
            top_cat = max(cat_c, key=cat_c.get)  # type: ignore[arg-type]
            tips.append(f"Category tilt: {top_cat} is {cat_c[top_cat]:.0f}%. Add complementary categories.")
        if top_weight > 8:
            tips.append(f"Single-stock effective weight ~{top_weight:.1f}% across funds — monitor concentration risk.")
        if len(repeated) > 10:
            tips.append(f"{len(repeated)} stocks appear in multiple funds — overlap is material.")
        if not tips:
            tips.append("Overlap looks manageable. Maintain diversification and rebalance periodically.")
        tips.append("Suggested alternatives: mix large-cap index + flexi-cap active + mid/small satellite (different AMCs).")
        return tips
