"""Data provenance — classify where the inputs to a calculation came from.

`FundService` falls back to a synthetic GBM NAV path when every live provider
fails (`fund_service.get_nav_history`) and to sample holdings when the Groww
lookup fails (`fund_service.get_holdings`). Both fallbacks return data that
looks entirely ordinary, so a Sharpe ratio, an efficient frontier or a sector
chart can be computed from fabricated inputs with nothing on screen to say so.

The source of every fetch is already tracked per fund; this module classifies
those source strings and summarises them so any page can disclose them the same
way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

# Values emitted by mfapi_client, holdings_client and fund_service.
FABRICATED_SOURCES = {"synthetic", "sample"}
STALE_SOURCES = {"disk_cache_stale"}
UNKNOWN_SOURCES = {"unknown", "", "mfapi_error"}

LIVE = "live"
STALE = "stale"
FABRICATED = "fabricated"
UNKNOWN = "unknown"

# Shown instead of the raw source string.
SOURCE_LABELS = {
    "mfapi": "mfapi.in",
    "tigzig": "TigZig",
    "amfi": "AMFI",
    "disk_cache": "cached",
    "disk_cache_stale": "cached (stale)",
    "sqlite": "local DB",
    "groww": "Groww",
    "groww_cache": "Groww (cached)",
    "synthetic": "SYNTHETIC",
    "sample": "SAMPLE",
    "unknown": "unknown",
}


def classify(source: Optional[str]) -> str:
    """One of LIVE / STALE / FABRICATED / UNKNOWN for a raw source string."""
    s = (source or "").strip().lower()
    if s in FABRICATED_SOURCES:
        return FABRICATED
    if s in STALE_SOURCES:
        return STALE
    if s in UNKNOWN_SOURCES:
        return UNKNOWN
    return LIVE


def label_for(source: Optional[str]) -> str:
    s = (source or "unknown").strip().lower()
    return SOURCE_LABELS.get(s, s)


@dataclass
class Provenance:
    """Which source fed the NAV and holdings of each fund in a calculation.

    Both maps are keyed by a display label (scheme name where available, else
    the AMFI code) so the UI can name the affected funds.
    """

    nav: dict[str, str] = field(default_factory=dict)
    holdings: dict[str, str] = field(default_factory=dict)

    def _of_kind(self, mapping: dict[str, str], kind: str) -> list[str]:
        return sorted(k for k, v in mapping.items() if classify(v) == kind)

    @property
    def fabricated_nav(self) -> list[str]:
        return self._of_kind(self.nav, FABRICATED)

    @property
    def fabricated_holdings(self) -> list[str]:
        return self._of_kind(self.holdings, FABRICATED)

    @property
    def stale_nav(self) -> list[str]:
        return self._of_kind(self.nav, STALE)

    @property
    def has_fabricated(self) -> bool:
        return bool(self.fabricated_nav or self.fabricated_holdings)

    @property
    def is_empty(self) -> bool:
        return not self.nav and not self.holdings

    def source_counts(self, kind: str = "nav") -> dict[str, int]:
        """How many funds came from each raw source, for a one-line summary."""
        mapping = self.nav if kind == "nav" else self.holdings
        counts: dict[str, int] = {}
        for src in mapping.values():
            key = label_for(src)
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    def to_dict(self) -> dict[str, Any]:
        return {
            "nav": dict(self.nav),
            "holdings": dict(self.holdings),
            "fabricated_nav": self.fabricated_nav,
            "fabricated_holdings": self.fabricated_holdings,
            "stale_nav": self.stale_nav,
            "has_fabricated": self.has_fabricated,
            "nav_counts": self.source_counts("nav"),
            "holdings_counts": self.source_counts("holdings"),
        }

    @classmethod
    def from_dict(cls, data: Optional[dict[str, Any]]) -> "Provenance":
        if not data:
            return cls()
        return cls(nav=dict(data.get("nav") or {}), holdings=dict(data.get("holdings") or {}))

    @classmethod
    def from_service(
        cls,
        fund_service: Any,
        entries: Iterable[tuple[str, str]],
        *,
        include_holdings: bool = True,
    ) -> "Provenance":
        """Collect tracked sources for `(label, amfi_code)` pairs.

        Only reads sources already recorded by earlier fetches — it never
        triggers a lookup of its own, so calling it is free.
        """
        prov = cls()
        for label, code in entries:
            code = str(code or "").strip()
            if not code:
                continue
            name = label or code
            try:
                nav_src = fund_service.get_nav_source(code)
            except Exception:
                nav_src = "unknown"
            if classify(nav_src) != UNKNOWN:
                prov.nav[name] = nav_src
            if include_holdings:
                try:
                    hold_src = fund_service.get_holdings_source(code)
                except Exception:
                    hold_src = "unknown"
                if classify(hold_src) != UNKNOWN:
                    prov.holdings[name] = hold_src
        return prov
