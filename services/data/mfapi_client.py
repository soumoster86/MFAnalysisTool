"""Historical NAV client via mfapi.in (primary) with TigZig AMFI API fallback."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings
from utils.logging_config import get_logger

logger = get_logger(__name__)


class MFAPIClient:
    """
    Fetch full historical NAV for an AMFI scheme code.

    Primary: https://api.mfapi.in/mf/{scheme_code}
    Fallback: https://api.tigzig.com/mf/v1/nav?scheme={scheme_code}
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        fallback_url: Optional[str] = None,
        cache_dir: Optional[Path] = None,
        cache_hours: Optional[int] = None,
        timeout: int = 60,
    ) -> None:
        self.base_url = (base_url or settings.mfapi_base_url).rstrip("/")
        self.fallback_url = (fallback_url or settings.tigzig_nav_url).rstrip("/")
        self.cache_dir = Path(cache_dir or settings.data_cache_dir) / "nav_history"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_hours = cache_hours if cache_hours is not None else settings.nav_cache_hours
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "MFAnalysisTool/1.0 (research; local)",
                "Accept": "application/json",
            }
        )

    def _cache_path(self, amfi_code: str) -> Path:
        return self.cache_dir / f"nav_{amfi_code}.csv"

    def _cache_fresh(self, path: Path) -> bool:
        if not path.exists():
            return False
        age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
        return age < timedelta(hours=self.cache_hours)

    def load_cached(self, amfi_code: str) -> Optional[pd.Series]:
        path = self._cache_path(str(amfi_code))
        if not path.exists():
            return None
        try:
            df = pd.read_csv(path, parse_dates=["date"])
            if df.empty:
                return None
            s = df.set_index("date")["nav"].astype(float).sort_index()
            s.index = pd.to_datetime(s.index).tz_localize(None)
            s.name = str(amfi_code)
            s.attrs["source"] = "disk_cache"
            s.attrs["amfi_code"] = str(amfi_code)
            return s
        except Exception as exc:
            logger.warning("Failed reading NAV cache for {}: {}", amfi_code, exc)
            return None

    def save_cache(self, amfi_code: str, series: pd.Series) -> None:
        path = self._cache_path(str(amfi_code))
        df = pd.DataFrame({"date": series.index, "nav": series.values})
        df.to_csv(path, index=False)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def _get_json(self, url: str, params: Optional[dict] = None) -> Any:
        resp = self.session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def fetch_meta(self, amfi_code: str) -> dict[str, Any]:
        """Return scheme meta from mfapi (fund house, category, ISINs, name)."""
        url = f"{self.base_url}/mf/{amfi_code}"
        try:
            # Prefer latest endpoint for lightweight meta; fall back to full
            try:
                payload = self._get_json(f"{url}/latest")
            except Exception:
                payload = self._get_json(url)
            meta = payload.get("meta") or {}
            return {
                "amfi_code": str(meta.get("scheme_code") or amfi_code),
                "scheme_name": meta.get("scheme_name"),
                "amc": meta.get("fund_house"),
                "scheme_type": meta.get("scheme_type"),
                "scheme_category": meta.get("scheme_category"),
                "isin_growth": meta.get("isin_growth"),
                "isin_div": meta.get("isin_div_reinvestment"),
                "source": "mfapi",
            }
        except Exception as exc:
            logger.warning("mfapi meta failed for {}: {}", amfi_code, exc)
            return {"amfi_code": str(amfi_code), "source": "mfapi_error"}

    def _parse_mfapi_data(self, payload: dict, amfi_code: str) -> pd.Series:
        rows = payload.get("data") or []
        if not rows:
            raise ValueError(f"No NAV rows from mfapi for {amfi_code}")
        dates: list[pd.Timestamp] = []
        navs: list[float] = []
        for row in rows:
            try:
                d = datetime.strptime(str(row["date"]), "%d-%m-%Y")
                nav = float(row["nav"])
                if nav > 0:
                    dates.append(pd.Timestamp(d))
                    navs.append(nav)
            except (KeyError, TypeError, ValueError):
                continue
        if not dates:
            raise ValueError(f"Could not parse NAV rows for {amfi_code}")
        s = pd.Series(navs, index=pd.DatetimeIndex(dates), name=str(amfi_code)).sort_index()
        s = s[~s.index.duplicated(keep="last")]
        meta = payload.get("meta") or {}
        if meta.get("scheme_name"):
            s.name = meta["scheme_name"]
        s.attrs["source"] = "mfapi"
        s.attrs["amfi_code"] = str(amfi_code)
        s.attrs["meta"] = meta
        return s

    def _fetch_mfapi(
        self,
        amfi_code: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> pd.Series:
        url = f"{self.base_url}/mf/{amfi_code}"
        params: dict[str, str] = {}
        if start_date:
            params["startDate"] = start_date.strftime("%Y-%m-%d")
        if end_date:
            params["endDate"] = end_date.strftime("%Y-%m-%d")
        logger.info("Fetching NAV history from mfapi for {}", amfi_code)
        payload = self._get_json(url, params=params or None)
        if str(payload.get("status", "")).upper() not in ("SUCCESS", "OK", ""):
            # Some responses omit status or use SUCCESS
            if not payload.get("data"):
                raise ValueError(f"mfapi status={payload.get('status')} for {amfi_code}")
        return self._parse_mfapi_data(payload, amfi_code)

    def _fetch_tigzig(
        self,
        amfi_code: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> pd.Series:
        params: dict[str, str] = {"scheme": str(amfi_code)}
        if start_date:
            params["since"] = start_date.isoformat()
        if end_date:
            params["to"] = end_date.isoformat()
        logger.info("Fetching NAV history from TigZig for {}", amfi_code)
        payload = self._get_json(self.fallback_url, params=params)
        rows = payload.get("data") or []
        if not rows:
            raise ValueError(f"No NAV rows from TigZig for {amfi_code}")
        dates = []
        navs = []
        for row in rows:
            try:
                d = pd.to_datetime(row["date"])
                nav = float(row["nav"])
                if nav > 0:
                    dates.append(d)
                    navs.append(nav)
            except (KeyError, TypeError, ValueError):
                continue
        s = pd.Series(navs, index=pd.DatetimeIndex(dates), name=str(amfi_code)).sort_index()
        s = s[~s.index.duplicated(keep="last")]
        if payload.get("scheme_name"):
            s.name = payload["scheme_name"]
        s.attrs["source"] = "tigzig"
        s.attrs["amfi_code"] = str(amfi_code)
        return s

    def get_nav_history(
        self,
        amfi_code: str,
        *,
        years: Optional[float] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        force_refresh: bool = False,
        prefer_cache: bool = True,
    ) -> pd.Series:
        """
        Return historical NAV series (DatetimeIndex, float).

        Order: disk cache → mfapi.in → TigZig → raise.
        """
        code = str(amfi_code).strip()
        if not code:
            raise ValueError("amfi_code is required")

        if prefer_cache and not force_refresh:
            path = self._cache_path(code)
            if self._cache_fresh(path):
                cached = self.load_cached(code)
                if cached is not None and len(cached) > 5:
                    return self._trim(cached, years=years, start_date=start_date, end_date=end_date)

        errors: list[str] = []
        series: Optional[pd.Series] = None

        try:
            series = self._fetch_mfapi(code, start_date=start_date, end_date=end_date)
        except Exception as exc:
            errors.append(f"mfapi: {exc}")
            logger.warning("mfapi NAV failed for {}: {}", code, exc)

        if series is None or series.empty:
            try:
                series = self._fetch_tigzig(code, start_date=start_date, end_date=end_date)
            except Exception as exc:
                errors.append(f"tigzig: {exc}")
                logger.warning("TigZig NAV failed for {}: {}", code, exc)

        if series is None or series.empty:
            # Stale cache is better than nothing
            cached = self.load_cached(code)
            if cached is not None and len(cached) > 5:
                cached.attrs["source"] = "disk_cache_stale"
                return self._trim(cached, years=years, start_date=start_date, end_date=end_date)
            raise RuntimeError(
                f"Unable to fetch historical NAV for {code}. " + "; ".join(errors)
            )

        self.save_cache(code, series)
        return self._trim(series, years=years, start_date=start_date, end_date=end_date)

    @staticmethod
    def _trim(
        series: pd.Series,
        *,
        years: Optional[float] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> pd.Series:
        s = series.sort_index()
        if start_date:
            s = s[s.index >= pd.Timestamp(start_date)]
        if end_date:
            s = s[s.index <= pd.Timestamp(end_date)]
        if years is not None and len(s) > 0 and start_date is None:
            cutoff = s.index.max() - pd.DateOffset(days=int(years * 365.25))
            s = s[s.index >= cutoff]
        # preserve attrs
        for k, v in series.attrs.items():
            s.attrs[k] = v
        return s
