"""Portfolio holdings client — Groww public scheme API (unofficial)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings
from utils.logging_config import get_logger

logger = get_logger(__name__)


class HoldingsClient:
    """
    Resolve AMFI schemes to portfolio holdings via Groww web APIs.

    Flow:
      1. Map AMFI code → Groww search_id (search by scheme name, match scheme_code)
      2. Fetch scheme detail (v2) including holdings[], AUM, TER, manager, etc.
      3. Cache JSON on disk

    Note: Groww APIs are unofficial and may change. Failures fall through to sample data.
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        cache_hours: Optional[int] = None,
        timeout: int = 45,
    ) -> None:
        self.cache_dir = Path(cache_dir or settings.data_cache_dir) / "holdings"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_hours = (
            cache_hours if cache_hours is not None else settings.holdings_cache_hours
        )
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://groww.in/",
            }
        )
        self._id_map_path = self.cache_dir / "amfi_to_groww.json"
        self._id_map: dict[str, str] = self._load_id_map()

    def _load_id_map(self) -> dict[str, str]:
        if self._id_map_path.exists():
            try:
                return json.loads(self._id_map_path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_id_map(self) -> None:
        self._id_map_path.write_text(json.dumps(self._id_map, indent=2), encoding="utf-8")

    def _detail_cache_path(self, amfi_code: str) -> Path:
        return self.cache_dir / f"scheme_{amfi_code}.json"

    def _cache_fresh(self, path: Path) -> bool:
        if not path.exists():
            return False
        age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
        return age < timedelta(hours=self.cache_hours)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def _get_json(self, url: str, params: Optional[dict] = None) -> Any:
        resp = self.session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def search_groww(self, query: str, size: int = 10) -> list[dict[str, Any]]:
        """Search Groww schemes by name."""
        url = "https://groww.in/v1/api/search/v3/query/global/st_p_query"
        payload = self._get_json(
            url,
            params={"query": query, "entity_type": "scheme", "size": size},
        )
        content = (payload.get("data") or {}).get("content") or []
        return content

    def resolve_search_id(
        self,
        amfi_code: str,
        scheme_name: Optional[str] = None,
        force: bool = False,
    ) -> Optional[str]:
        """Map AMFI code → Groww search_id."""
        code = str(amfi_code)
        if not force and code in self._id_map:
            return self._id_map[code]

        candidates_q: list[str] = []
        if scheme_name:
            # Clean plan suffixes for better search hit rate
            cleaned = re.sub(
                r"\s*-\s*(Direct|Regular).*",
                "",
                scheme_name,
                flags=re.IGNORECASE,
            ).strip()
            candidates_q.append(cleaned)
            candidates_q.append(scheme_name)
        candidates_q.append(code)

        for q in candidates_q:
            try:
                results = self.search_groww(q, size=12)
            except Exception as exc:
                logger.warning("Groww search failed for '{}': {}", q, exc)
                continue
            for item in results:
                sid = item.get("search_id") or item.get("id")
                if not sid:
                    continue
                # Verify by fetching detail and matching scheme_code
                try:
                    detail = self.fetch_scheme_detail(str(sid), use_cache=True)
                    sc = str(detail.get("scheme_code") or detail.get("direct_scheme_code") or "")
                    if sc == code:
                        self._id_map[code] = str(sid)
                        self._save_id_map()
                        return str(sid)
                    # Also accept if query was exact code and first result
                except Exception:
                    continue
            # If only one result for a name search, accept and verify later
            if scheme_name and results:
                sid = results[0].get("search_id") or results[0].get("id")
                if sid:
                    try:
                        detail = self.fetch_scheme_detail(str(sid), use_cache=True)
                        sc = str(detail.get("scheme_code") or "")
                        if sc == code or not sc:
                            self._id_map[code] = str(sid)
                            self._save_id_map()
                            return str(sid)
                    except Exception:
                        pass

        # Brute: try search with shortened tokens
        if scheme_name:
            tokens = [t for t in re.split(r"[\s\-]+", scheme_name) if len(t) > 3][:4]
            if tokens:
                try:
                    results = self.search_groww(" ".join(tokens[:3]), size=15)
                    for item in results:
                        sid = item.get("search_id") or item.get("id")
                        if not sid:
                            continue
                        detail = self.fetch_scheme_detail(str(sid), use_cache=True)
                        if str(detail.get("scheme_code") or "") == code:
                            self._id_map[code] = str(sid)
                            self._save_id_map()
                            return str(sid)
                except Exception as exc:
                    logger.warning("Groww fallback search failed: {}", exc)

        return None

    def fetch_scheme_detail(
        self,
        search_id: str,
        *,
        use_cache: bool = True,
        force: bool = False,
    ) -> dict[str, Any]:
        """Fetch Groww scheme payload (prefer v2 for structured holdings)."""
        cache_path = self.cache_dir / f"groww_{search_id}.json"
        if use_cache and not force and self._cache_fresh(cache_path):
            try:
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        # v2 has structured holdings dicts; v1 has array rows
        url = f"https://groww.in/v1/api/data/mf/web/v2/scheme/search/{quote(search_id)}"
        logger.info("Fetching Groww scheme detail {}", search_id)
        detail = self._get_json(url)
        try:
            cache_path.write_text(json.dumps(detail), encoding="utf-8")
        except Exception:
            pass
        return detail

    def get_scheme_bundle(
        self,
        amfi_code: str,
        scheme_name: Optional[str] = None,
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """
        Return normalized bundle:
          holdings (DataFrame), meta (dict), source, portfolio_date
        """
        code = str(amfi_code)
        cache_path = self._detail_cache_path(code)
        if not force_refresh and self._cache_fresh(cache_path):
            try:
                raw = json.loads(cache_path.read_text(encoding="utf-8"))
                return self._normalize_bundle(raw, code, source="groww_cache")
            except Exception:
                pass

        sid = self.resolve_search_id(code, scheme_name=scheme_name, force=force_refresh)
        if not sid:
            raise LookupError(
                f"Could not resolve Groww search_id for AMFI {code} ({scheme_name})"
            )

        detail = self.fetch_scheme_detail(sid, force=force_refresh)
        # Ensure scheme_code matches when possible
        sc = str(detail.get("scheme_code") or "")
        if sc and sc != code:
            logger.warning(
                "Groww scheme_code {} != requested AMFI {} for {}", sc, code, sid
            )

        try:
            cache_path.write_text(json.dumps(detail), encoding="utf-8")
        except Exception:
            pass

        return self._normalize_bundle(detail, code, source="groww")

    def _normalize_bundle(
        self, detail: dict[str, Any], amfi_code: str, source: str
    ) -> dict[str, Any]:
        holdings_df = self._parse_holdings(detail.get("holdings") or [])
        portfolio_date = None
        if not holdings_df.empty and "as_of_date" in holdings_df.columns:
            portfolio_date = holdings_df["as_of_date"].dropna().astype(str).head(1)
            portfolio_date = portfolio_date.iloc[0] if len(portfolio_date) else None

        aum = detail.get("aum")
        try:
            aum_cr = float(aum) if aum is not None else None
            # Groww often reports AUM already in crores for large funds; if huge, convert
            if aum_cr is not None and aum_cr > 1_000_000:
                aum_cr = aum_cr / 1e7  # rupees → crore
        except (TypeError, ValueError):
            aum_cr = None

        expense = detail.get("expense_ratio")
        try:
            expense = float(expense) if expense is not None else None
        except (TypeError, ValueError):
            expense = None

        meta = {
            "amfi_code": str(detail.get("scheme_code") or amfi_code),
            "scheme_name": detail.get("scheme_name"),
            "amc": detail.get("fund_house") or detail.get("amc"),
            "category": detail.get("category"),
            "subcategory": detail.get("sub_category"),
            "fund_manager": detail.get("fund_manager"),
            "expense_ratio": expense,
            "aum_cr": aum_cr,
            "exit_load": detail.get("exit_load"),
            "benchmark": detail.get("benchmark_name") or detail.get("benchmark"),
            "launch_date": detail.get("launch_date"),
            "min_sip": detail.get("min_sip_investment") or detail.get("min_investment_amount"),
            "min_lumpsum": detail.get("min_investment_amount"),
            "portfolio_turnover": detail.get("portfolio_turnover"),
            "nav": detail.get("nav"),
            "nav_date": detail.get("nav_date"),
            "groww_search_id": detail.get("search_id"),
            "isin_growth": detail.get("isin"),
            "riskometer": detail.get("nfo_risk") or detail.get("crisil_rating"),
            "source": source,
        }

        # Asset mix from holdings
        if not holdings_df.empty and "asset_type" in holdings_df.columns:
            mix = holdings_df.groupby("asset_type")["weight_pct"].sum().to_dict()
            meta["equity_allocation"] = mix.get("Equity")
            meta["debt_allocation"] = mix.get("Debt")
            meta["cash_allocation"] = mix.get("Cash")
            meta["international_exposure"] = mix.get("International")

        return {
            "holdings": holdings_df,
            "meta": meta,
            "raw_keys": list(detail.keys()),
            "source": source,
            "portfolio_date": portfolio_date,
        }

    def _parse_holdings(self, holdings: list[Any]) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        for h in holdings:
            if isinstance(h, dict):
                name = h.get("company_name") or h.get("name") or h.get("instrument_name")
                weight = h.get("corpus_per")
                if weight is None:
                    weight = h.get("weight_pct") or h.get("weight")
                sector = h.get("sector_name") or h.get("sector")
                nature = (h.get("nature_name") or h.get("instrument_name") or "Equity")
                mcap = h.get("market_cap") or h.get("rating_market_cap")
                as_of = h.get("portfolio_date")
                isin = h.get("isin")
            elif isinstance(h, (list, tuple)) and len(h) >= 9:
                # v1 array form:
                # [scheme_code, date, name, nature, sector, instrument, ?, mkt_val, weight, ...]
                name = h[2]
                as_of = h[1]
                nature = h[3]
                sector = h[4]
                weight = h[8]
                mcap = h[9] if len(h) > 9 else None
                isin = None
            else:
                continue

            try:
                w = float(weight) if weight is not None else None
            except (TypeError, ValueError):
                w = None
            if not name or w is None:
                continue

            asset_type = self._asset_type(str(nature), str(name))
            country = "International" if asset_type == "International" else "India"
            mcap_label = self._normalize_mcap(mcap, asset_type)

            as_of_date = None
            if as_of:
                try:
                    as_of_date = pd.to_datetime(as_of).date().isoformat()
                except Exception:
                    as_of_date = str(as_of)[:10]

            rows.append(
                {
                    "security_name": str(name).strip(),
                    "isin": isin,
                    "sector": sector or "Other",
                    "market_cap": mcap_label,
                    "weight_pct": round(float(w), 4),
                    "country": country,
                    "asset_type": asset_type,
                    "as_of_date": as_of_date,
                }
            )

        if not rows:
            return pd.DataFrame(
                columns=[
                    "security_name",
                    "isin",
                    "sector",
                    "market_cap",
                    "weight_pct",
                    "country",
                    "asset_type",
                    "as_of_date",
                ]
            )
        df = pd.DataFrame(rows)
        # Collapse duplicate security names
        df = (
            df.groupby(
                ["security_name", "sector", "market_cap", "country", "asset_type"],
                as_index=False,
            )
            .agg({"weight_pct": "sum", "isin": "first", "as_of_date": "first"})
            .sort_values("weight_pct", ascending=False)
            .reset_index(drop=True)
        )
        return df

    @staticmethod
    def _asset_type(nature: str, name: str) -> str:
        n = f"{nature} {name}".lower()
        if any(x in n for x in ("treasury", "g-sec", "gilt", "bond", "debenture", "ncd", "cp ", "cd ", "debt")):
            return "Debt"
        if any(x in n for x in ("cash", "treps", "reverse repo", "net current", "receivable", "cblo")):
            return "Cash"
        if any(x in n for x in ("us ", "usa", "global", "international", "nasdaq", "nyse", "adr", "gdr")):
            return "International"
        if "gold" in n or "silver" in n or "commodity" in n:
            return "Commodity"
        if "equity" in n or "share" in n or "stock" in n:
            return "Equity"
        return "Equity" if "equity" in nature.lower() else nature.title()[:32] or "Other"

    @staticmethod
    def _normalize_mcap(mcap: Any, asset_type: str) -> str:
        if asset_type != "Equity":
            return "N/A"
        if mcap is None or (isinstance(mcap, float) and pd.isna(mcap)):
            return "Unclassified"
        s = str(mcap).strip().lower()
        if not s or s in ("none", "null", "nan"):
            return "Unclassified"
        if "large" in s:
            return "Large"
        if "mid" in s:
            return "Mid"
        if "small" in s:
            return "Small"
        return str(mcap)[:32]
