"""yfinance wrappers for benchmarks and synthetic fund NAV history."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from config.settings import settings
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Common India market benchmarks
BENCHMARK_TICKERS = {
    "NIFTY 50": "^NSEI",
    "NIFTY NEXT 50": "^NSMIDCP",  # approximate; may fail
    "SENSEX": "^BSESN",
    "NIFTY BANK": "^NSEBANK",
    "NIFTY MIDCAP 100": "NIFTY_MIDCAP_100.NS",
    "GOLD": "GC=F",
    "USDINR": "INR=X",
}


class YFinanceClient:
    """Fetch market data via yfinance with CSV cache."""

    def __init__(self, cache_dir: Optional[Path] = None) -> None:
        self.cache_dir = Path(cache_dir or settings.data_cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_file(self, ticker: str) -> Path:
        safe = ticker.replace("^", "IDX_").replace("=", "_").replace("/", "_")
        return self.cache_dir / f"yf_{safe}.csv"

    def download(
        self,
        ticker: str,
        period: str = "5y",
        force: bool = False,
    ) -> pd.Series:
        """Return adjusted close series indexed by date."""
        cache = self._cache_file(ticker)
        if cache.exists() and not force:
            age_h = (datetime.now() - datetime.fromtimestamp(cache.stat().st_mtime)).total_seconds() / 3600
            if age_h < settings.nav_cache_hours:
                df = pd.read_csv(cache, parse_dates=["Date"])
                s = df.set_index("Date")["Close"].astype(float)
                s.name = ticker
                return s.sort_index()

        try:
            import yfinance as yf

            logger.info("Downloading yfinance {}", ticker)
            data = yf.download(ticker, period=period, progress=False, auto_adjust=True)
            if data is None or data.empty:
                raise ValueError(f"No data for {ticker}")
            # Handle multi-index columns from recent yfinance
            if isinstance(data.columns, pd.MultiIndex):
                close = data["Close"]
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]
            else:
                close = data["Close"]
            close = close.dropna().astype(float)
            close.index = pd.to_datetime(close.index).tz_localize(None)
            out = pd.DataFrame({"Date": close.index, "Close": close.values})
            out.to_csv(cache, index=False)
            s = close
            s.name = ticker
            return s.sort_index()
        except Exception as exc:
            logger.warning("yfinance failed for {}: {}", ticker, exc)
            if cache.exists():
                df = pd.read_csv(cache, parse_dates=["Date"])
                s = df.set_index("Date")["Close"].astype(float)
                s.name = ticker
                return s.sort_index()
            # Synthetic fallback so UI never hard-crashes
            return self._synthetic_series(ticker)

    def get_benchmark(self, name: str = "NIFTY 50", period: str = "5y") -> pd.Series:
        ticker = BENCHMARK_TICKERS.get(name, name)
        s = self.download(ticker, period=period)
        s.name = name
        return s

    def _synthetic_series(self, name: str, days: int = 252 * 5) -> pd.Series:
        """GBM synthetic price path for offline demos."""
        rng = np.random.default_rng(abs(hash(name)) % (2**32))
        dates = pd.bdate_range(end=datetime.now().date(), periods=days)
        mu, sigma = 0.12 / 252, 0.15 / np.sqrt(252)
        rets = rng.normal(mu, sigma, size=days)
        prices = 100 * np.cumprod(1 + rets)
        s = pd.Series(prices, index=dates, name=name)
        return s

    def synthetic_fund_nav(
        self,
        scheme_name: str,
        latest_nav: float = 100.0,
        years: float = 5.0,
        annual_return: float = 0.12,
        annual_vol: float = 0.16,
        benchmark: Optional[pd.Series] = None,
        beta: float = 0.95,
        seed: Optional[int] = None,
    ) -> pd.Series:
        """
        Build a realistic historical NAV path ending at latest_nav.

        If benchmark provided, generate returns = alpha + beta * bench + residual.
        """
        days = int(years * 252)
        rng = np.random.default_rng(seed if seed is not None else abs(hash(scheme_name)) % (2**32))
        dates = pd.bdate_range(end=datetime.now().date(), periods=days)

        if benchmark is not None and len(benchmark) > 50:
            b = benchmark.reindex(dates).ffill().bfill()
            b_rets = b.pct_change().fillna(0).values
            alpha_d = (annual_return - beta * 0.12) / 252
            resid = rng.normal(0, annual_vol * 0.4 / np.sqrt(252), size=len(dates))
            rets = alpha_d + beta * b_rets + resid
        else:
            rets = rng.normal(annual_return / 252, annual_vol / np.sqrt(252), size=days)

        # Scale path so last value == latest_nav
        path = np.cumprod(1 + rets)
        path = path / path[-1] * latest_nav
        return pd.Series(path, index=dates, name=scheme_name)
