"""Feature engineering for NAV-based ML models."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


class FeatureEngineer:
    """Build leakage-safe features from NAV / return series."""

    def __init__(self, trading_days: int = 252) -> None:
        self.td = trading_days

    def from_nav(
        self,
        nav: pd.Series,
        benchmark: Optional[pd.Series] = None,
        expense_ratio: Optional[float] = None,
        aum_cr: Optional[float] = None,
        manager_tenure: Optional[float] = None,
    ) -> pd.DataFrame:
        s = nav.dropna().astype(float).sort_index()
        rets = s.pct_change()
        df = pd.DataFrame({"nav": s, "ret": rets})

        for w in (5, 21, 63, 126, 252):
            df[f"mom_{w}"] = s.pct_change(w)
            df[f"vol_{w}"] = rets.rolling(w).std() * np.sqrt(self.td)
            df[f"ma_{w}"] = s.rolling(w).mean()
            df[f"ma_ratio_{w}"] = s / df[f"ma_{w}"] - 1

        # Rolling Sharpe / Sortino (approx)
        for w in (63, 252):
            mean = rets.rolling(w).mean() * self.td
            vol = rets.rolling(w).std() * np.sqrt(self.td)
            df[f"roll_sharpe_{w}"] = mean / vol.replace(0, np.nan)
            downside = rets.where(rets < 0, 0.0)
            dvol = downside.rolling(w).std() * np.sqrt(self.td)
            df[f"roll_sortino_{w}"] = mean / dvol.replace(0, np.nan)

        # Drawdown
        peak = s.cummax()
        df["drawdown"] = (s - peak) / peak
        df["max_dd_252"] = df["drawdown"].rolling(252).min()

        # RSI(14)
        delta = s.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        df["rsi_14"] = 100 - (100 / (1 + rs))

        # MACD
        ema12 = s.ewm(span=12, adjust=False).mean()
        ema26 = s.ewm(span=26, adjust=False).mean()
        df["macd"] = ema12 - ema26
        df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
        df["macd_hist"] = df["macd"] - df["macd_signal"]

        if benchmark is not None:
            b = benchmark.reindex(s.index).ffill().bfill()
            b_rets = b.pct_change()
            for w in (63, 252):
                cov = rets.rolling(w).cov(b_rets)
                var = b_rets.rolling(w).var()
                df[f"beta_{w}"] = cov / var.replace(0, np.nan)
                df[f"alpha_{w}"] = (rets.rolling(w).mean() - df[f"beta_{w}"] * b_rets.rolling(w).mean()) * self.td
            df["bench_ret_21"] = b_rets.rolling(21).sum()

        # Static features broadcast
        if expense_ratio is not None:
            df["expense_ratio"] = expense_ratio
        if aum_cr is not None:
            df["log_aum"] = np.log1p(aum_cr)
        if manager_tenure is not None:
            df["manager_tenure"] = manager_tenure

        # Forward return labels (for training only — shift carefully)
        df["fwd_ret_21"] = s.pct_change(21).shift(-21)
        df["fwd_ret_63"] = s.pct_change(63).shift(-63)
        df["fwd_vol_63"] = rets.shift(-63).rolling(63).std().shift(-62) * np.sqrt(self.td)

        return df

    def make_supervised(
        self,
        feature_df: pd.DataFrame,
        target_col: str = "fwd_ret_63",
        dropna: bool = True,
    ) -> tuple[pd.DataFrame, pd.Series]:
        """Return X, y with leakage-prone forward columns removed from X."""
        forward_cols = [c for c in feature_df.columns if c.startswith("fwd_")]
        y = feature_df[target_col]
        X = feature_df.drop(columns=forward_cols + ["nav", "ret"], errors="ignore")
        # Drop non-numeric
        X = X.select_dtypes(include=[np.number])
        if dropna:
            mask = X.notna().all(axis=1) & y.notna()
            return X.loc[mask], y.loc[mask]
        return X, y
