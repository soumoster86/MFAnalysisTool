"""Import CAS holdings into portfolio analyzer format with AMFI resolution."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from services.data.cas_parser import CASHolding, CASParseResult, CASParser
from services.data.fund_service import FundService
from utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class ImportedHolding:
    amfi_code: str
    scheme_name: str
    invested_amount: float
    units: float
    sip_amount: float = 0.0
    current_nav: Optional[float] = None
    market_value: Optional[float] = None
    folio: Optional[str] = None
    holding_type: str = "soa"
    match_score: float = 0.0
    match_method: str = "unmatched"
    cas_scheme_name: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_portfolio_row(self) -> dict[str, Any]:
        """Shape expected by PortfolioAnalyzerService / session state."""
        invested = self.invested_amount
        # Demat CAS often shows invested=0; use market value so weights work
        if invested <= 0 and self.market_value and self.market_value > 0:
            invested = float(self.market_value)
        return {
            "amfi_code": self.amfi_code,
            "scheme_name": self.scheme_name,
            "invested_amount": round(invested, 2),
            "units": round(self.units or 0.0, 4),
            "sip_amount": self.sip_amount,
            "current_nav": self.current_nav,
            "market_value": self.market_value,
            "folio": self.folio,
            "holding_type": self.holding_type,
            "match_method": self.match_method,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ImportResult:
    cas: dict[str, Any]
    holdings: list[ImportedHolding] = field(default_factory=list)
    unmatched: list[dict[str, Any]] = field(default_factory=list)
    merged_count: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_portfolio_holdings(self) -> list[dict[str, Any]]:
        return [h.to_portfolio_row() for h in self.holdings if h.amfi_code]

    def to_dict(self) -> dict[str, Any]:
        return {
            "cas": self.cas,
            "holdings": [h.to_dict() for h in self.holdings],
            "unmatched": self.unmatched,
            "merged_count": self.merged_count,
            "warnings": self.warnings,
            "portfolio_holdings": self.to_portfolio_holdings(),
        }


class PortfolioImportService:
    """CAS → portfolio holdings with fuzzy AMFI scheme matching."""

    def __init__(self, fund_service: Optional[FundService] = None) -> None:
        self.funds = fund_service or FundService()
        self.parser = CASParser()
        self._name_cache: dict[str, Optional[tuple[str, str, float, str]]] = {}

    def import_cas_pdf(
        self,
        source: Any,
        *,
        filename: Optional[str] = None,
        include_demat: bool = True,
        include_soa: bool = True,
        include_zero_balance: bool = False,
        merge_duplicates: bool = True,
        min_match_score: float = 0.45,
    ) -> ImportResult:
        cas = self.parser.parse(
            source, filename=filename, include_zero_balance=include_zero_balance
        )
        return self.import_cas_result(
            cas,
            include_demat=include_demat,
            include_soa=include_soa,
            merge_duplicates=merge_duplicates,
            min_match_score=min_match_score,
        )

    def import_cas_result(
        self,
        cas: CASParseResult,
        *,
        include_demat: bool = True,
        include_soa: bool = True,
        merge_duplicates: bool = True,
        min_match_score: float = 0.45,
    ) -> ImportResult:
        warnings = list(cas.warnings)
        selected: list[CASHolding] = []
        for h in cas.active_holdings:
            if h.holding_type == "soa" and include_soa:
                selected.append(h)
            elif h.holding_type == "demat" and include_demat:
                selected.append(h)

        if not selected:
            warnings.append("No holdings selected after SoA/Demat filters.")

        imported: list[ImportedHolding] = []
        unmatched: list[dict[str, Any]] = []

        for h in selected:
            match = self.resolve_scheme(h.scheme_name, min_score=min_match_score)
            if match is None:
                unmatched.append(h.to_dict())
                warnings.append(f"Unmatched scheme: {h.scheme_name[:80]}")
                # Keep a placeholder with empty amfi so user can fix manually
                imported.append(
                    ImportedHolding(
                        amfi_code="",
                        scheme_name=h.scheme_name,
                        invested_amount=h.invested_amount,
                        units=h.units,
                        current_nav=h.nav,
                        market_value=h.market_value,
                        folio=h.folio or h.client_id,
                        holding_type=h.holding_type,
                        match_score=0.0,
                        match_method="unmatched",
                        cas_scheme_name=h.scheme_name,
                        warnings=["Could not map to AMFI scheme code"],
                    )
                )
                continue

            code, official_name, score, method = match
            imported.append(
                ImportedHolding(
                    amfi_code=code,
                    scheme_name=official_name,
                    invested_amount=h.invested_amount,
                    units=h.units,
                    current_nav=h.nav,
                    market_value=h.market_value,
                    folio=h.folio or h.client_id,
                    holding_type=h.holding_type,
                    match_score=score,
                    match_method=method,
                    cas_scheme_name=h.scheme_name,
                )
            )

        merged_count = 0
        if merge_duplicates:
            imported, merged_count = self._merge_by_amfi(imported)

        # Drop pure unmatched from portfolio application list is caller's choice
        return ImportResult(
            cas=cas.to_dict(include_zero=False),
            holdings=imported,
            unmatched=unmatched,
            merged_count=merged_count,
            warnings=warnings,
        )

    def resolve_scheme(
        self, scheme_name: str, min_score: float = 0.45
    ) -> Optional[tuple[str, str, float, str]]:
        """Return (amfi_code, official_name, score, method) or None."""
        key = scheme_name.strip().lower()
        if key in self._name_cache:
            return self._name_cache[key]

        sl = scheme_name.lower()
        want_direct = "direct" in sl or "dir " in sl or "-dir" in sl or "diran" in sl
        want_growth = "growth" in sl and "idcw" not in sl and "dividend" not in sl
        cas_amc = self._detect_amc(scheme_name)

        queries = self._build_search_queries(scheme_name)
        best: Optional[tuple[str, str, float, str]] = None

        for q, method_hint in queries:
            frames = []
            # Prefer Direct Growth universe when CAS implies Direct
            if want_direct:
                try:
                    frames.append(
                        self.funds.search_funds(q, limit=40, direct_growth_only=True)
                    )
                except Exception as exc:
                    logger.warning("AMFI search failed for '{}': {}", q, exc)
            try:
                frames.append(
                    self.funds.search_funds(q, limit=40, direct_growth_only=False)
                )
            except Exception as exc:
                logger.warning("AMFI search failed for '{}': {}", q, exc)

            for df in frames:
                if df is None or df.empty:
                    continue
                for _, row in df.iterrows():
                    cand_name = str(row.get("scheme_name") or "")
                    cl = cand_name.lower()

                    # Hard filters for plan type
                    if want_direct and "direct" not in cl:
                        continue
                    if want_growth and ("idcw" in cl or "dividend" in cl):
                        continue
                    if want_growth and "growth" not in cl and "idcw" not in sl:
                        # allow index/ETF names without explicit Growth word
                        if "etf" not in cl and "index" not in cl and "bees" not in cl:
                            continue

                    score = self._similarity(scheme_name, cand_name)
                    cand_amc = self._detect_amc(cand_name)
                    if cas_amc and cand_amc:
                        if cas_amc == cand_amc:
                            score += 0.15
                        else:
                            # Wrong AMC — almost always reject
                            score -= 0.45
                    elif cas_amc and cand_amc is None:
                        # soft: require cas amc token present in candidate
                        if cas_amc not in cl and cas_amc.split()[0] not in cl:
                            score -= 0.25

                    if want_direct and "direct" in cl:
                        score += 0.06
                    if want_growth and "growth" in cl:
                        score += 0.04
                    if "regular" in cl and want_direct:
                        score -= 0.2

                    # Penalize extra style words not present in CAS name
                    for extra in (
                        "equal weight",
                        "next 50",
                        "midcap 150",
                        "smallcap",
                        "large mid",
                        "focused",
                        "value",
                        "contra",
                    ):
                        if extra in cl and extra not in sl:
                            # allow midcap 150 only if cas mentions midcap/mid
                            if extra == "midcap 150" and ("midcap" in sl or "mid cap" in sl):
                                continue
                            if extra == "next 50" and "next 50" in sl:
                                continue
                            score -= 0.22

                    # Require key category tokens when present in CAS
                    for must in ("small cap", "mid cap", "flexi cap", "large cap", "liquid", "arbitrage"):
                        if must in sl and must not in cl:
                            # smallcap vs small cap
                            compact = must.replace(" ", "")
                            if compact not in cl.replace(" ", ""):
                                score -= 0.15

                    score = max(0.0, min(1.0, score))
                    if best is None or score > best[2]:
                        best = (
                            str(row["amfi_code"]),
                            cand_name,
                            score,
                            method_hint,
                        )

        # Stricter floor when AMC was detected (avoid Navi→SBI style errors)
        floor = min_score
        if cas_amc:
            floor = max(min_score, 0.52)

        if best and best[2] >= floor:
            self._name_cache[key] = best
            return best
        self._name_cache[key] = None
        return None

    # Common AMC aliases seen in CAS / AMFI names
    _AMC_ALIASES: list[tuple[str, tuple[str, ...]]] = [
        ("parag parikh", ("parag parikh", "ppfas")),
        ("aditya birla", ("aditya birla", "absl", "birla sun")),
        ("nippon", ("nippon", "reliance")),
        ("icici", ("icici",)),
        ("hdfc", ("hdfc",)),
        ("sbi", ("sbi ", "sbi-")),
        ("axis", ("axis",)),
        ("mirae", ("mirae",)),
        ("tata", ("tata",)),
        ("quant", ("quant",)),
        ("franklin", ("franklin", "frank ")),
        ("hsbc", ("hsbc", "l&t")),
        ("canara", ("canara",)),
        ("dsp", ("dsp",)),
        ("bandhan", ("bandhan", "idfc")),
        ("motilal", ("motilal",)),
        ("navi", ("navi",)),
        ("whiteoak", ("whiteoak", "white oak")),
        ("zerodha", ("zerodha",)),
        ("angel one", ("angel one", "angelone")),
        ("kotak", ("kotak",)),  # before mahindra — "Kotak Mahindra MF"
        ("mahindra", ("mahindra manulife", "mahindra", "manulife")),
        ("uti", ("uti",)),
        ("invesco", ("invesco",)),
        ("edelweiss", ("edelweiss",)),
        ("pgim", ("pgim",)),
        ("baroda", ("baroda", "bnp")),
        ("groww", ("groww",)),
    ]

    def _detect_amc(self, name: str) -> Optional[str]:
        """Pick AMC by earliest / longest alias match (avoids Kotak Mahindra → Manulife)."""
        n = f" {name.lower()} "
        best: Optional[str] = None
        best_pos = 10**9
        best_len = 0
        for canonical, aliases in self._AMC_ALIASES:
            for a in aliases:
                # pad to reduce partial token false positives
                needle = a if a.endswith(" ") else a
                pos = n.find(needle)
                if pos < 0:
                    pos = n.find(a)
                if pos >= 0 and (pos < best_pos or (pos == best_pos and len(a) > best_len)):
                    best = canonical
                    best_pos = pos
                    best_len = len(a)
        return best

    def _build_search_queries(self, scheme_name: str) -> list[tuple[str, str]]:
        """Generate progressive search strings from CAS scheme names."""
        name = scheme_name.strip()
        queries: list[tuple[str, str]] = []

        def norm(s: str) -> str:
            # AMFI search is substring on name; hyphens/spacing vary a lot
            s = s.replace("-", " ").replace("/", " ")
            s = re.sub(r"\s+", " ", s).strip()
            return s

        # Demat style: "HDFC MF-HDFC FLEXI CAP FUND-DIRECT-GROWTH"
        demat_clean = re.sub(r"^[A-Z0-9 &./]+ MF-", "", name, flags=re.I)
        demat_clean = re.sub(r"^[A-Z0-9 &./]+ MUTUAL FUND-", "", demat_clean, flags=re.I)
        demat_clean = norm(demat_clean)

        def scrub(s: str) -> str:
            s = norm(s)
            # Drop parenthetical renames: (Formerly known as ...)
            s = re.sub(r"\([^)]*\)", " ", s)
            s = re.sub(
                r"\b(formerly known as|erstwhile|plan|option|diran|super inst|"
                r"direct pl|dir pl|dv pl|growth opt|growth option)\b",
                " ",
                s,
                flags=re.I,
            )
            s = re.sub(r"\b(direct|growth)\b", " ", s, flags=re.I)
            s = re.sub(r"\s+", " ", s).strip()
            return s

        amc = self._detect_amc(name)
        # Prefer short high-signal queries first (full legal names often fail substring search)
        core_name = scrub(demat_clean or name)
        variants: list[tuple[str, str]] = [
            (core_name, "core_name"),
            (norm(demat_clean), "demat_clean"),
            (scrub(name), "scrub_full"),
            (norm(name), "norm_full"),
        ]

        tokens = re.findall(r"[A-Za-z0-9]+", core_name)
        stop = {
            "mf", "fund", "funds", "plan", "direct", "growth", "regular",
            "option", "the", "and", "of", "india", "mutual", "temp", "frank",
            "known", "as", "formerly",
        }
        core = [t for t in tokens if t.lower() not in stop and len(t) > 1]
        if len(core) >= 2:
            variants.insert(0, (" ".join(core[:6]), "core_tokens"))
            if amc:
                variants.insert(0, (f"{amc} {' '.join(core[:5])}", "amc_plus_core"))
        if len(core) >= 3:
            variants.append((" ".join(core[:4]), "core4"))

        nl = f"{name} {demat_clean}".lower()
        for phrase in (
            "small cap", "mid cap", "flexi cap", "large cap", "large & mid",
            "money market", "corporate bond", "arbitrage", "elss", "tax saver",
            "nifty 50", "midcap 150", "banking and psu", "equity savings",
            "multi asset", "liquid", "short duration", "active fund",
            "large mid cap", "nifty next 50",
        ):
            if phrase in nl:
                if amc:
                    variants.insert(0, (f"{amc} {phrase}", "amc_phrase"))
                variants.append((phrase, "phrase"))

        seen: set[str] = set()
        for v, method in variants:
            v = norm(v)
            if len(v) < 3:
                continue
            k = v.lower()
            if k in seen:
                continue
            seen.add(k)
            queries.append((v, method))
        return queries

    def _similarity(self, a: str, b: str) -> float:
        """Token Jaccard + substring boost."""
        ta = self._tokens(a)
        tb = self._tokens(b)
        if not ta or not tb:
            return 0.0
        inter = len(ta & tb)
        union = len(ta | tb)
        jacc = inter / union if union else 0.0
        # coverage of query tokens in candidate
        cov = inter / len(ta) if ta else 0.0
        score = 0.55 * jacc + 0.45 * cov
        al, bl = a.lower(), b.lower()
        # distinctive multi-word phrases
        for phrase in ("small cap", "mid cap", "flexi cap", "large cap", "money market",
                       "corporate bond", "elss", "index", "etf", "nifty 50", "midcap 150"):
            if phrase in al and phrase in bl:
                score += 0.05
            elif phrase in al and phrase not in bl:
                score -= 0.05
        return max(0.0, min(1.0, score))

    @staticmethod
    def _tokens(s: str) -> set[str]:
        stop = {
            "mf", "fund", "funds", "plan", "direct", "growth", "regular",
            "option", "the", "and", "of", "india", "mutual", "scheme",
            "open", "ended", "an", "a", "pl", "dir", "dv",
        }
        toks = re.findall(r"[a-z0-9]+", s.lower())
        return {t for t in toks if t not in stop and len(t) > 1}

    def _merge_by_amfi(
        self, holdings: list[ImportedHolding]
    ) -> tuple[list[ImportedHolding], int]:
        """Combine same AMFI code across SoA + Demat folios."""
        buckets: dict[str, ImportedHolding] = {}
        unmatched_rows: list[ImportedHolding] = []
        merges = 0
        for h in holdings:
            if not h.amfi_code:
                unmatched_rows.append(h)
                continue
            if h.amfi_code not in buckets:
                buckets[h.amfi_code] = h
                continue
            base = buckets[h.amfi_code]
            base.units = (base.units or 0) + (h.units or 0)
            base.invested_amount = (base.invested_amount or 0) + (h.invested_amount or 0)
            base.market_value = (base.market_value or 0) + (h.market_value or 0)
            if base.units and base.market_value:
                base.current_nav = round(base.market_value / base.units, 4)
            base.holding_type = "merged"
            base.folio = ", ".join(
                x for x in [base.folio, h.folio] if x
            )[:120]
            base.warnings.append(f"Merged with {h.cas_scheme_name[:40]}")
            merges += 1
        return list(buckets.values()) + unmatched_rows, merges
