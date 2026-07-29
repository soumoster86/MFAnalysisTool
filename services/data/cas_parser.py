"""
MFCentral Consolidated Account Summary (CAS) PDF parser.

Supports MFCentralCASSummary_v2.x layout:
  - SoA Holdings tables (Folio No. + scheme + invested/units/NAV/market value)
  - Demat Holdings tables (Client Id + scheme + units/market value)

Privacy: personal fields (PAN, email, address, mobile) are parsed only for
display masking and are not required for portfolio import.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO, Optional, Union

import pdfplumber

from utils.logging_config import get_logger

logger = get_logger(__name__)

SourcePath = Union[str, Path, bytes, BinaryIO]


@dataclass
class CASHolding:
    """Single scheme line from CAS."""

    scheme_name: str
    folio: Optional[str] = None
    client_id: Optional[str] = None
    invested_amount: float = 0.0
    units: float = 0.0
    nav: Optional[float] = None
    nav_date: Optional[str] = None
    market_value: float = 0.0
    gain_loss: Optional[float] = None
    gain_loss_pct: Optional[float] = None
    holding_type: str = "soa"  # soa | demat
    isin: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CASParseResult:
    """Full parse result from an MFCentral CAS Summary PDF."""

    as_on_date: Optional[str] = None
    investor_name: Optional[str] = None
    pan_masked: Optional[str] = None
    holdings: list[CASHolding] = field(default_factory=list)
    soa_total: Optional[float] = None
    demat_total: Optional[float] = None
    page_count: int = 0
    warnings: list[str] = field(default_factory=list)
    source_filename: Optional[str] = None

    @property
    def active_holdings(self) -> list[CASHolding]:
        """Holdings with positive market value or units."""
        return [
            h
            for h in self.holdings
            if (h.market_value and h.market_value > 0.01)
            or (h.units and h.units > 1e-6)
        ]

    def to_dict(self, include_zero: bool = False) -> dict[str, Any]:
        rows = self.holdings if include_zero else self.active_holdings
        return {
            "as_on_date": self.as_on_date,
            "investor_name": self.investor_name,
            "pan_masked": self.pan_masked,
            "page_count": self.page_count,
            "soa_total": self.soa_total,
            "demat_total": self.demat_total,
            "holdings_count": len(rows),
            "holdings": [h.to_dict() for h in rows],
            "warnings": self.warnings,
            "source_filename": self.source_filename,
            "total_market_value": round(sum(h.market_value for h in rows), 2),
            "total_invested": round(
                sum(h.invested_amount for h in rows if h.invested_amount > 0), 2
            ),
        }


class CASParser:
    """Parse MFCentral Consolidated Account Summary PDFs."""

    HEADER_MARKERS = ("folio no", "scheme details", "client id", "invested value")

    def parse(
        self,
        source: SourcePath,
        *,
        filename: Optional[str] = None,
        include_zero_balance: bool = False,
    ) -> CASParseResult:
        path_or_buf = self._openable(source)
        result = CASParseResult(source_filename=filename)

        with pdfplumber.open(path_or_buf) as doc:
            result.page_count = len(doc.pages)
            full_text_parts: list[str] = []
            for page in doc.pages:
                text = page.extract_text() or ""
                full_text_parts.append(text)
                tables = page.extract_tables() or []
                for tbl in tables:
                    self._ingest_table(tbl, result)

            full_text = "\n".join(full_text_parts)
            self._extract_header_meta(full_text, result)
            self._extract_section_totals(full_text, result)

        if not include_zero_balance:
            before = len(result.holdings)
            result.holdings = result.active_holdings
            dropped = before - len(result.holdings)
            if dropped:
                result.warnings.append(
                    f"Excluded {dropped} zero-balance scheme line(s)."
                )

        if not result.holdings:
            result.warnings.append(
                "No holdings rows found. Ensure this is an MFCentral CAS Summary PDF "
                "(not a password-protected CAS detailed statement)."
            )
        else:
            logger.info(
                "Parsed CAS: {} holdings, SoA total={}, Demat total={}",
                len(result.holdings),
                result.soa_total,
                result.demat_total,
            )
        return result

    # ------------------------------------------------------------------ open
    def _openable(self, source: SourcePath):
        if isinstance(source, (bytes, bytearray)):
            return BytesIO(source)
        if hasattr(source, "read"):
            data = source.read()  # type: ignore[union-attr]
            if isinstance(data, str):
                data = data.encode("utf-8")
            return BytesIO(data)
        return str(source)

    # ----------------------------------------------------------------- header
    def _extract_header_meta(self, text: str, result: CASParseResult) -> None:
        m = re.search(r"As on Date:\s*([0-9]{1,2}-[A-Za-z]{3}-[0-9]{4})", text, re.I)
        if m:
            result.as_on_date = m.group(1)

        pan = re.search(r"PAN\s*:?\s*([A-Z]{5}[0-9]{4}[A-Z])", text, re.I)
        if pan:
            raw = pan.group(1).upper()
            result.pan_masked = f"{raw[:3]}XXXX{raw[-1]}"

        # Name: often on its own line after PAN (MFCentral layout)
        name_m = re.search(
            r"PAN\s*:?\s*[A-Z0-9]{10}[^\n]*\n\s*([A-Z][A-Za-z .']{2,60})\s*\n",
            text,
        )
        if not name_m:
            name_m = re.search(
                r"\n([A-Z]{2,}(?:\s+[A-Z]{2,}){0,4})\s*\n(?:Flat|House|Vill|S/O|D/O|C/O|\d)",
                text,
            )
        if name_m:
            cand = name_m.group(1).strip()
            if cand.upper() not in {"CONSOLIDATED ACCOUNT SUMMARY", "SOA HOLDINGS", "DEMAT HOLDINGS"}:
                result.investor_name = cand

    def _extract_section_totals(self, text: str, result: CASParseResult) -> None:
        # "Total 19,43,777.14" appears after SoA and Demat sections
        totals = re.findall(r"\bTotal\s+([0-9,]+\.\d{2})", text)
        nums = [self._parse_number(t) for t in totals]
        nums = [n for n in nums if n and n > 0]
        if len(nums) >= 1:
            result.soa_total = nums[0]
        if len(nums) >= 2:
            result.demat_total = nums[1]

    # ----------------------------------------------------------------- tables
    def _ingest_table(self, table: list[list[Any]], result: CASParseResult) -> None:
        if not table or len(table) < 2:
            return
        header_cells = [self._norm_cell(c) for c in table[0]]
        header_joined = " ".join(header_cells).lower()
        if "scheme" not in header_joined:
            return
        if "folio" not in header_joined and "client" not in header_joined:
            # not a holdings table
            if "invested" not in header_joined:
                return

        colmap = self._map_columns(header_cells)
        if "scheme" not in colmap:
            return

        holding_type = "demat" if "client" in header_joined else "soa"

        for raw_row in table[1:]:
            if not raw_row or all(not self._norm_cell(c) for c in raw_row):
                continue
            cells = [self._norm_cell(c) for c in raw_row]
            # skip total row
            scheme = cells[colmap["scheme"]] if colmap["scheme"] < len(cells) else ""
            if not scheme or scheme.lower().startswith("total"):
                continue
            # join multi-line scheme names
            scheme = re.sub(r"\s+", " ", scheme).strip()
            if len(scheme) < 4:
                continue

            def col(name: str) -> str:
                idx = colmap.get(name)
                if idx is None or idx >= len(cells):
                    return ""
                return cells[idx]

            invested = self._parse_number(col("invested")) or 0.0
            units = self._parse_number(col("units")) or 0.0
            nav = self._parse_number(col("nav"))
            mkt = self._parse_number(col("market")) or 0.0
            gain_abs, gain_pct = self._parse_gain(col("gain"))
            folio = col("folio") or None
            client = col("client") or None
            nav_date = col("nav_date") or None

            # Demat often has NAV blank/0; derive if possible
            if (nav is None or nav == 0) and units and mkt:
                nav = round(mkt / units, 4) if units else nav

            # Skip pure empty shells already zeroed
            if invested == 0 and units == 0 and mkt == 0:
                # still record for optional include_zero; filter later
                pass

            result.holdings.append(
                CASHolding(
                    scheme_name=scheme,
                    folio=folio,
                    client_id=client,
                    invested_amount=invested,
                    units=units,
                    nav=nav,
                    nav_date=nav_date,
                    market_value=mkt,
                    gain_loss=gain_abs,
                    gain_loss_pct=gain_pct,
                    holding_type=holding_type,
                )
            )

    def _map_columns(self, headers: list[str]) -> dict[str, int]:
        mapping: dict[str, int] = {}
        for i, h in enumerate(headers):
            hl = h.lower().replace("\n", " ")
            if "folio" in hl:
                mapping["folio"] = i
            elif "client" in hl:
                mapping["client"] = i
            elif "scheme" in hl:
                mapping["scheme"] = i
            elif "invested" in hl:
                mapping["invested"] = i
            elif "balance" in hl or "unit" in hl:
                mapping["units"] = i
            elif "nav date" in hl or (hl.strip() == "nav date"):
                mapping["nav_date"] = i
            elif hl.strip() == "nav" or (hl.startswith("nav") and "date" not in hl):
                mapping["nav"] = i
            elif "market" in hl:
                mapping["market"] = i
            elif "gain" in hl or "loss" in hl:
                mapping["gain"] = i
        return mapping

    @staticmethod
    def _norm_cell(c: Any) -> str:
        if c is None:
            return ""
        return str(c).replace("\xa0", " ").strip()

    @staticmethod
    def _parse_number(value: str) -> Optional[float]:
        if value is None:
            return None
        s = str(value).strip()
        if not s or s in ("-", "—", "NA", "N/A"):
            return None
        # Take first line if multi-line (gain cells)
        s = s.split("\n")[0].strip()
        neg = False
        if s.startswith("(") and s.endswith(")"):
            neg = True
            s = s[1:-1]
        s = s.replace(",", "").replace("₹", "").replace("INR", "").strip()
        s = re.sub(r"[^0-9.\-]", "", s)
        if not s or s in (".", "-", "-."):
            return None
        try:
            num = float(s)
            return -num if neg else num
        except ValueError:
            return None

    @staticmethod
    def _parse_gain(value: str) -> tuple[Optional[float], Optional[float]]:
        if not value:
            return None, None
        lines = [ln.strip() for ln in str(value).split("\n") if ln.strip()]
        abs_v = CASParser._parse_number(lines[0]) if lines else None
        pct_v = None
        joined = " ".join(lines)
        m = re.search(r"\(([+\-]?[0-9.,]+)\s*%\)", joined)
        if m:
            try:
                pct_v = float(m.group(1).replace(",", ""))
            except ValueError:
                pct_v = None
        return abs_v, pct_v


def is_likely_cas_pdf(source: SourcePath) -> bool:
    """Quick heuristic check without full parse."""
    try:
        parser = CASParser()
        path = parser._openable(source)
        with pdfplumber.open(path) as doc:
            if not doc.pages:
                return False
            text = (doc.pages[0].extract_text() or "").lower()
            return "consolidated account" in text or "mfcentral" in text or "cas" in text
    except Exception:
        return False
