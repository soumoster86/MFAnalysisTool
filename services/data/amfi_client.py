"""AMFI NAV data client — downloads and parses official NAVAll.txt."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings
from utils.logging_config import get_logger

logger = get_logger(__name__)

# AMFI file sections look like:
# Scheme Code;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date


class AMFIClient:
    """Fetch and cache AMFI scheme NAVs."""

    def __init__(
        self,
        url: Optional[str] = None,
        cache_dir: Optional[Path] = None,
        cache_hours: Optional[int] = None,
    ) -> None:
        self.url = url or settings.amfi_nav_url
        self.cache_dir = Path(cache_dir or settings.data_cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_hours = cache_hours if cache_hours is not None else settings.nav_cache_hours
        self._df: Optional[pd.DataFrame] = None

    @property
    def cache_path(self) -> Path:
        return self.cache_dir / "amfi_nav_all.csv"

    def _cache_fresh(self) -> bool:
        if not self.cache_path.exists():
            return False
        mtime = datetime.fromtimestamp(self.cache_path.stat().st_mtime)
        return datetime.now() - mtime < timedelta(hours=self.cache_hours)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def _download_raw(self) -> str:
        logger.info("Downloading AMFI NAV from {}", self.url)
        headers = {
            "User-Agent": "MFAnalysisTool/1.0 (research; +https://localhost)",
            "Accept": "text/plain,*/*",
        }
        resp = requests.get(self.url, headers=headers, timeout=60)
        resp.raise_for_status()
        # AMFI sometimes serves latin-1 / mixed encodings
        try:
            return resp.content.decode("utf-8")
        except UnicodeDecodeError:
            return resp.content.decode("latin-1", errors="replace")

    def parse_nav_text(self, text: str) -> pd.DataFrame:
        """Parse AMFI NAVAll semi-colon format into a DataFrame."""
        rows: list[dict] = []
        current_amc: Optional[str] = None
        date_pat = re.compile(r"\d{2}-\w{3}-\d{4}")

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            # AMC header lines have no semicolons (or few)
            if ";" not in line:
                current_amc = line
                continue
            parts = [p.strip() for p in line.split(";")]
            if len(parts) < 6:
                continue
            # Skip header
            if parts[0].lower().startswith("scheme code"):
                continue
            try:
                code = parts[0]
                if not code.isdigit():
                    continue
                isin_growth = parts[1] or None
                isin_div = parts[2] or None
                name = parts[3]
                nav_str = parts[4].replace(",", "")
                nav = float(nav_str) if nav_str and nav_str not in ("N.A.", "NA", "-") else None
                date_str = parts[5]
                nav_date = None
                if date_pat.fullmatch(date_str) or date_str:
                    try:
                        nav_date = datetime.strptime(date_str, "%d-%b-%Y").date()
                    except ValueError:
                        nav_date = None
                if nav is None:
                    continue
                rows.append(
                    {
                        "amfi_code": code,
                        "isin_growth": isin_growth if isin_growth not in ("-", "") else None,
                        "isin_div": isin_div if isin_div not in ("-", "") else None,
                        "scheme_name": name,
                        "nav": nav,
                        "nav_date": nav_date,
                        "amc": current_amc,
                    }
                )
            except (ValueError, IndexError):
                continue

        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.drop_duplicates(subset=["amfi_code"], keep="last")
            df = self._enrich_categories(df)
        logger.info("Parsed {} AMFI schemes", len(df))
        return df

    def _enrich_categories(self, df: pd.DataFrame) -> pd.DataFrame:
        """Heuristic category tags from scheme name (AMFI file lacks category)."""

        def categorize(name: str) -> tuple[str, str]:
            n = name.lower()
            if "liquid" in n:
                return "Debt", "Liquid"
            if "overnight" in n:
                return "Debt", "Overnight"
            if "money market" in n:
                return "Debt", "Money Market"
            if "gilt" in n or "g-sec" in n:
                return "Debt", "Gilt"
            if "corporate bond" in n:
                return "Debt", "Corporate Bond"
            if "banking and psu" in n or "banking & psu" in n:
                return "Debt", "Banking & PSU"
            if "short duration" in n or "short term" in n:
                return "Debt", "Short Duration"
            if "ultra short" in n:
                return "Debt", "Ultra Short"
            if "low duration" in n:
                return "Debt", "Low Duration"
            if "credit risk" in n:
                return "Debt", "Credit Risk"
            if "dynamic bond" in n:
                return "Debt", "Dynamic Bond"
            if "index fund" in n or "etf" in n or "bees" in n:
                if "nifty" in n or "sensex" in n or "equity" in n:
                    return "Index/ETF", "Equity Index"
                return "Index/ETF", "Other Index"
            if "flexi cap" in n or "flexicap" in n:
                return "Equity", "Flexi Cap"
            if "multi cap" in n or "multicap" in n:
                return "Equity", "Multi Cap"
            if "large & mid" in n or "large and mid" in n:
                return "Equity", "Large & Mid Cap"
            if "large cap" in n or "bluechip" in n or "blue chip" in n:
                return "Equity", "Large Cap"
            if "mid cap" in n or "midcap" in n:
                return "Equity", "Mid Cap"
            if "small cap" in n or "smallcap" in n:
                return "Equity", "Small Cap"
            if "elss" in n or "tax saver" in n or "taxsaver" in n:
                return "Equity", "ELSS"
            if "focused" in n:
                return "Equity", "Focused"
            if "value" in n or "contra" in n:
                return "Equity", "Value/Contra"
            if "dividend yield" in n:
                return "Equity", "Dividend Yield"
            if "sector" in n or "pharma" in n or "banking" in n or "technology" in n or "infrastructure" in n:
                return "Equity", "Sectoral/Thematic"
            if "thematic" in n or "consumption" in n or "manufacturing" in n:
                return "Equity", "Sectoral/Thematic"
            if "hybrid" in n or "balanced" in n or "aggressive hybrid" in n:
                return "Hybrid", "Hybrid"
            if "arbitrage" in n:
                return "Hybrid", "Arbitrage"
            if "multi asset" in n:
                return "Hybrid", "Multi Asset"
            if "conservative hybrid" in n:
                return "Hybrid", "Conservative Hybrid"
            if "international" in n or "global" in n or "us " in n or "nasdaq" in n:
                return "Other", "International"
            if "gold" in n or "silver" in n:
                return "Other", "Commodity"
            if "equity" in n:
                return "Equity", "Other Equity"
            if "debt" in n or "bond" in n or "income" in n:
                return "Debt", "Other Debt"
            return "Other", "Unclassified"

        cats = df["scheme_name"].apply(categorize)
        df = df.copy()
        df["category"] = cats.apply(lambda x: x[0])
        df["subcategory"] = cats.apply(lambda x: x[1])
        # Prefer Direct Growth plans for analytics defaults
        df["is_direct"] = df["scheme_name"].str.contains("Direct", case=False, na=False)
        df["is_growth"] = df["scheme_name"].str.contains("Growth", case=False, na=False)
        return df

    def load(self, force_refresh: bool = False) -> pd.DataFrame:
        """Load schemes from cache or network."""
        if self._df is not None and not force_refresh:
            return self._df

        if not force_refresh and self._cache_fresh():
            logger.info("Loading AMFI data from cache {}", self.cache_path)
            self._df = pd.read_csv(self.cache_path, parse_dates=["nav_date"])
            return self._df

        try:
            text = self._download_raw()
            df = self.parse_nav_text(text)
            if df.empty:
                raise ValueError("Empty AMFI parse result")
            df.to_csv(self.cache_path, index=False)
            self._df = df
            return df
        except Exception as exc:
            logger.warning("AMFI download failed: {}. Trying cache/sample.", exc)
            if self.cache_path.exists():
                self._df = pd.read_csv(self.cache_path, parse_dates=["nav_date"])
                return self._df
            # Fall back to bundled sample
            sample = settings.sample_data_dir / "amfi_sample.csv"
            if sample.exists():
                self._df = pd.read_csv(sample, parse_dates=["nav_date"])
                return self._df
            raise

    def search(self, query: str, limit: int = 25, direct_growth_only: bool = False) -> pd.DataFrame:
        df = self.load()
        q = query.strip().lower()
        mask = df["scheme_name"].str.lower().str.contains(re.escape(q), na=False)
        if q.isdigit():
            mask = mask | (df["amfi_code"].astype(str) == q)
        out = df.loc[mask]
        if direct_growth_only:
            out = out[out["is_direct"] & out["is_growth"]]
        return out.head(limit)

    def get_by_code(self, amfi_code: str) -> Optional[pd.Series]:
        df = self.load()
        hit = df[df["amfi_code"].astype(str) == str(amfi_code)]
        if hit.empty:
            return None
        return hit.iloc[0]

    def list_categories(self) -> pd.DataFrame:
        df = self.load()
        return (
            df.groupby(["category", "subcategory"])
            .size()
            .reset_index(name="count")
            .sort_values(["category", "count"], ascending=[True, False])
        )
