"""Tests for MFCentral CAS parser (synthetic table ingestion — no PII)."""

from __future__ import annotations

from services.data.cas_parser import CASHolding, CASParseResult, CASParser
from services.portfolio.import_service import PortfolioImportService


def test_parse_inr_indian_commas() -> None:
    assert CASParser._parse_number("4,06,988.06") == 406988.06
    assert CASParser._parse_number("(235.31)") == -235.31
    assert CASParser._parse_number("1,488.212") == 1488.212


def test_parse_gain() -> None:
    abs_v, pct = CASParser._parse_gain("2,98,642.84\n(+73.38%)")
    assert abs_v == 298642.84
    assert pct == 73.38


def test_ingest_soa_table() -> None:
    parser = CASParser()
    result = CASParseResult()
    table = [
        [
            "Folio No.",
            "Scheme Details",
            "Invested Value\n(INR)",
            "Balance\nUnits",
            "NAV Date",
            "NAV",
            "Market Value\n(INR)",
            "Gain/Loss\n(Absolute)",
        ],
        [
            "11745931",
            "HDFC Small Cap Fund - Direct Growth Plan",
            "4,06,988.06",
            "4,434.444",
            "28-Jul-2026",
            "159.125",
            "7,05,630.90",
            "2,98,642.84\n(+73.38%)",
        ],
        [
            "42399285",
            "ICICI Prudential Corporate Bond Fund - Direct Plan - Growth",
            "3,00,000.00",
            "9,289.621",
            "28-Jul-2026",
            "33.4712",
            "3,10,934.76",
            "10,934.76\n(+3.64%)",
        ],
        ["", "Total", "7,06,988.06", "", "", "", "10,16,565.66", ""],
    ]
    parser._ingest_table(table, result)
    assert len(result.holdings) == 2
    h = result.holdings[0]
    assert h.holding_type == "soa"
    assert h.folio == "11745931"
    assert abs(h.invested_amount - 406988.06) < 0.01
    assert abs(h.units - 4434.444) < 0.001
    assert abs(h.market_value - 705630.90) < 0.01
    assert h.gain_loss_pct == 73.38


def test_ingest_demat_table() -> None:
    parser = CASParser()
    result = CASParseResult()
    table = [
        [
            "Client Id",
            "Scheme Details",
            "Invested Value\n(INR)",
            "Balance\nUnits",
            "NAV Date",
            "NAV",
            "Market Value\n(INR)",
            "Gain/Loss\n(Absolute)",
        ],
        [
            "12081600-09850099",
            "PPFAS MF-PARAG PARIKH FLEXI CAP FUND-DIRECT\nPLAN-GROWTH OPTION",
            "0.00",
            "904.3810",
            "",
            "0.0000",
            "81,711.73",
            "0.00\n(+0.00%)",
        ],
    ]
    parser._ingest_table(table, result)
    assert len(result.holdings) == 1
    h = result.holdings[0]
    assert h.holding_type == "demat"
    assert h.units == 904.381
    assert abs(h.market_value - 81711.73) < 0.01
    # NAV derived from market/units
    assert h.nav is not None and h.nav > 0


def test_active_holdings_filters_zero() -> None:
    r = CASParseResult(
        holdings=[
            CASHolding("A", units=0, market_value=0),
            CASHolding("B", units=10, market_value=1000),
        ]
    )
    assert len(r.active_holdings) == 1


def test_similarity_and_queries() -> None:
    svc = PortfolioImportService.__new__(PortfolioImportService)
    # bind methods only
    q = PortfolioImportService._build_search_queries(
        svc, "PPFAS MF-PARAG PARIKH FLEXI CAP FUND-DIRECT PLAN-GROWTH OPTION"
    )
    assert any("parag" in x[0].lower() or "flexi" in x[0].lower() for x in q)
    score = PortfolioImportService._similarity(
        svc,
        "Parag Parikh Flexi Cap Fund - Direct Plan Growth",
        "Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
    )
    assert score > 0.7


def test_merge_by_amfi() -> None:
    from services.portfolio.import_service import ImportedHolding

    svc = PortfolioImportService.__new__(PortfolioImportService)
    a = ImportedHolding(
        amfi_code="122639",
        scheme_name="PPFAS",
        invested_amount=1000,
        units=10,
        market_value=2000,
        holding_type="soa",
    )
    b = ImportedHolding(
        amfi_code="122639",
        scheme_name="PPFAS",
        invested_amount=500,
        units=5,
        market_value=1000,
        holding_type="demat",
    )
    merged, n = PortfolioImportService._merge_by_amfi(svc, [a, b])
    assert n == 1
    assert len(merged) == 1
    assert merged[0].units == 15
    assert merged[0].market_value == 3000
