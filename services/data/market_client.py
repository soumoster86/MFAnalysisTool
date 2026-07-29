"""NSE and BSE market data.

Two exchanges, because neither serves everything:

- **NSE** publishes a live board of every index in one call (`/api/allIndices`).
  Its per-symbol quote endpoint refuses programmatic access (403) regardless of
  cookie priming, so it is not used for stock quotes.
- **BSE** serves per-scrip quotes and a full equity snapshot (~2,700 rows with
  scrip code, name and last price), which also doubles as the name → scrip code
  index used to match fund holdings to listed companies.

Both are public, undocumented, rate-limited and prone to blocking. Every method
degrades to ``None`` or an empty frame instead of raising: market data enriches
the UI, it must never take a page down. Responses are cached on disk so a
blocked or slow exchange still renders the last known board.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import requests

from config.settings import settings
from utils.logging_config import get_logger

logger = get_logger(__name__)

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

NSE_HOME = "https://www.nseindia.com"
NSE_ALL_INDICES = f"{NSE_HOME}/api/allIndices"

BSE_HOME = "https://www.bseindia.com"
BSE_SCRIP_HEADER = (
    "https://api.bseindia.com/BseIndiaAPI/api/getScripHeaderData/w"
    "?Debtflag=&scripcode={code}&seriesid="
)
BSE_EQUITY_SNAPSHOT = (
    "https://api.bseindia.com/BseIndiaAPI/api/MktRGainerLoserData/w"
    "?GLtype=gainer&IndxGrp=&scripcode="
)

# Index names as the roadmap/benchmarks refer to them -> NSE's spelling.
INDEX_ALIASES = {
    "NIFTY 50": "NIFTY 50",
    "NIFTY50": "NIFTY 50",
    "NIFTY": "NIFTY 50",
    "NIFTY NEXT 50": "NIFTY NEXT 50",
    "NIFTY BANK": "NIFTY BANK",
    "BANKNIFTY": "NIFTY BANK",
    "NIFTY MIDCAP 100": "NIFTY MIDCAP 100",
    "NIFTY SMALLCAP 100": "NIFTY SMALLCAP 100",
    "NIFTY 500": "NIFTY 500",
    "NIFTY IT": "NIFTY IT",
}

# Suffixes that appear in fund holdings but not in exchange listings.
_HOLDING_NOISE = re.compile(
    r"\b(ltd|limited|ltd\.|the|and|&|co|corporation|corp|inc|plc)\b|[^a-z0-9 ]",
    re.IGNORECASE,
)


def _normalise_company(name: str) -> str:
    """Reduce a company name to a comparable key."""
    s = _HOLDING_NOISE.sub(" ", str(name or "").lower())
    return re.sub(r"\s+", " ", s).strip()


class MarketClient:
    """Live index and equity data from NSE + BSE, cached and fail-soft."""

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        cache_minutes: int = 15,
        timeout: int = 12,
    ) -> None:
        self.cache_dir = Path(cache_dir or settings.data_cache_dir) / "market"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_minutes = cache_minutes
        self.timeout = timeout
        self._nse_primed = False
        self._scrip_map: Optional[dict[str, dict[str, Any]]] = None
        self.last_error: Optional[str] = None

    # ------------------------------------------------------------------ cache
    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def _read_cache(self, key: str, max_age_minutes: Optional[int] = None) -> Optional[Any]:
        path = self._cache_path(key)
        if not path.exists():
            return None
        age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
        limit = self.cache_minutes if max_age_minutes is None else max_age_minutes
        if limit is not None and age > timedelta(minutes=limit):
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _read_cache_any_age(self, key: str) -> Optional[Any]:
        """Last known value regardless of age — used when the exchange blocks."""
        return self._read_cache(key, max_age_minutes=None) or self._load_raw(key)

    def _load_raw(self, key: str) -> Optional[Any]:
        path = self._cache_path(key)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _write_cache(self, key: str, payload: Any) -> None:
        try:
            self._cache_path(key).write_text(
                json.dumps(payload, default=str), encoding="utf-8"
            )
        except Exception as exc:
            logger.debug("Market cache write failed for {}: {}", key, exc)

    # -------------------------------------------------------------------- NSE
    def _nse_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": _BROWSER_UA,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Connection": "keep-alive",
            }
        )
        # NSE rejects API calls without the cookies its home page sets.
        try:
            session.get(NSE_HOME, timeout=self.timeout)
            self._nse_primed = True
        except Exception as exc:
            logger.debug("NSE priming failed: {}", exc)
        return session

    def get_indices(self, force: bool = False) -> pd.DataFrame:
        """Live board of every NSE index. Empty frame if unavailable."""
        if not force:
            cached = self._read_cache("nse_indices")
            if cached:
                return pd.DataFrame(cached)

        try:
            session = self._nse_session()
            resp = session.get(
                NSE_ALL_INDICES, timeout=self.timeout, headers={"Referer": NSE_HOME}
            )
            resp.raise_for_status()
            rows = resp.json().get("data") or []
            records = [
                {
                    "index": r.get("index"),
                    "last": r.get("last"),
                    "change": r.get("variation"),
                    "pct_change": r.get("percentChange"),
                    "open": r.get("open"),
                    "high": r.get("dayHigh"),
                    "low": r.get("dayLow"),
                    "year_high": r.get("yearHigh"),
                    "year_low": r.get("yearLow"),
                }
                for r in rows
                if r.get("index")
            ]
            if records:
                self._write_cache("nse_indices", records)
                self.last_error = None
                logger.info("NSE indices: {} rows", len(records))
                return pd.DataFrame(records)
        except Exception as exc:
            self.last_error = f"NSE indices unavailable: {type(exc).__name__}: {exc}"
            logger.warning(self.last_error)

        stale = self._read_cache_any_age("nse_indices")
        return pd.DataFrame(stale) if stale else pd.DataFrame()

    def get_index(self, name: str, force: bool = False) -> Optional[dict[str, Any]]:
        """One index by name, tolerating the common aliases."""
        target = INDEX_ALIASES.get(str(name).upper().strip(), str(name).strip()).upper()
        df = self.get_indices(force=force)
        if df.empty:
            return None
        match = df[df["index"].astype(str).str.upper() == target]
        if match.empty:
            return None
        return match.iloc[0].to_dict()

    # -------------------------------------------------------------------- BSE
    def _bse_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": _BROWSER_UA,
                "Accept": "application/json, text/plain, */*",
                "Referer": f"{BSE_HOME}/",
                "Origin": BSE_HOME,
            }
        )
        return session

    def get_equity_snapshot(self, force: bool = False) -> pd.DataFrame:
        """Full BSE equity board: scrip code, name, last price, day change."""
        if not force:
            cached = self._read_cache("bse_equities")
            if cached:
                return pd.DataFrame(cached)
        try:
            resp = self._bse_session().get(BSE_EQUITY_SNAPSHOT, timeout=self.timeout * 2)
            resp.raise_for_status()
            rows = (resp.json() or {}).get("Table") or []
            records = [
                {
                    "scrip_code": r.get("scrip_cd"),
                    "symbol": r.get("scripname"),
                    "name": r.get("LONG_NAME"),
                    "last": r.get("ltradert"),
                    "prev_close": r.get("prevdayclose"),
                    "change": r.get("change_val"),
                    "pct_change": r.get("change_percent"),
                    "high": r.get("highrate"),
                    "low": r.get("lowrate"),
                }
                for r in rows
                if r.get("scrip_cd") and r.get("LONG_NAME")
            ]
            if records:
                self._write_cache("bse_equities", records)
                self.last_error = None
                logger.info("BSE equity snapshot: {} rows", len(records))
                return pd.DataFrame(records)
        except Exception as exc:
            self.last_error = f"BSE snapshot unavailable: {type(exc).__name__}: {exc}"
            logger.warning(self.last_error)

        stale = self._read_cache_any_age("bse_equities")
        return pd.DataFrame(stale) if stale else pd.DataFrame()

    def _scrip_index(self, force: bool = False) -> dict[str, dict[str, Any]]:
        """Normalised company name -> BSE row, for matching fund holdings."""
        if self._scrip_map is not None and not force:
            return self._scrip_map
        df = self.get_equity_snapshot(force=force)
        mapping: dict[str, dict[str, Any]] = {}
        if not df.empty:
            for row in df.to_dict("records"):
                key = _normalise_company(row.get("name"))
                if key and key not in mapping:
                    mapping[key] = row
        self._scrip_map = mapping
        return mapping

    def get_equity_quote(self, name_or_symbol: str) -> Optional[dict[str, Any]]:
        """Live quote for a listed company, matched by name.

        Falls back to BSE's per-scrip endpoint when the company is in the index
        but the snapshot's price is missing.
        """
        key = _normalise_company(name_or_symbol)
        if not key:
            return None
        row = self._scrip_index().get(key)
        if row is None:
            # Try a prefix match — holdings often carry extra qualifiers.
            for candidate, value in self._scrip_index().items():
                if candidate.startswith(key) or key.startswith(candidate):
                    row = value
                    break
        if row is None:
            return None
        if row.get("last"):
            return row
        return self.get_scrip_quote(row["scrip_code"]) or row

    def get_scrip_quote(self, scrip_code: Any) -> Optional[dict[str, Any]]:
        """Per-scrip BSE quote (used when the snapshot lacks a price)."""
        key = f"bse_scrip_{scrip_code}"
        cached = self._read_cache(key)
        if cached:
            return cached
        try:
            resp = self._bse_session().get(
                BSE_SCRIP_HEADER.format(code=scrip_code), timeout=self.timeout
            )
            resp.raise_for_status()
            payload = resp.json() or {}
            rate = payload.get("CurrRate") or {}
            names = payload.get("Cmpname") or {}
            out = {
                "scrip_code": scrip_code,
                "name": names.get("FullN"),
                "symbol": names.get("ShortN"),
                "last": _as_float(rate.get("LTP")),
                "change": _as_float(rate.get("Chg")),
                "pct_change": _as_float(rate.get("PcChg")),
            }
            if out["last"] is not None:
                self._write_cache(key, out)
                return out
        except Exception as exc:
            logger.debug("BSE scrip {} failed: {}", scrip_code, exc)
        return None

    # ------------------------------------------------------------- enrichment
    def enrich_holdings(
        self, holdings: pd.DataFrame, *, limit: int = 40
    ) -> tuple[pd.DataFrame, int]:
        """Attach live last price and day change to fund holdings.

        Returns ``(frame, matched_count)``. Unmatched rows keep NaN rather than
        a guessed price — an unlisted or unmatched security must not be shown
        with someone else's quote.
        """
        if holdings is None or holdings.empty or "security_name" not in holdings.columns:
            return holdings, 0

        index = self._scrip_index()
        if not index:
            return holdings, 0

        out = holdings.copy()
        prices: list[Optional[float]] = []
        changes: list[Optional[float]] = []
        matched = 0
        for i, raw_name in enumerate(out["security_name"].tolist()):
            if i >= limit:
                prices.append(None)
                changes.append(None)
                continue
            quote = None
            key = _normalise_company(raw_name)
            if key:
                quote = index.get(key)
            if quote:
                matched += 1
                prices.append(_as_float(quote.get("last")))
                changes.append(_as_float(quote.get("pct_change")))
            else:
                prices.append(None)
                changes.append(None)

        out["last_price"] = prices
        out["day_change_pct"] = changes
        return out, matched


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").replace("+", "").strip())
    except (TypeError, ValueError):
        return None


_client: Optional[MarketClient] = None


def get_market_client() -> MarketClient:
    """Process-wide client so the scrip index is built once."""
    global _client
    if _client is None:
        _client = MarketClient()
    return _client
