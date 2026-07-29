"""Tests for holdings normalization (Groww payload shapes)."""

from __future__ import annotations

from pathlib import Path

from services.data.holdings_client import HoldingsClient


def test_parse_dict_holdings(tmp_path: Path) -> None:
    client = HoldingsClient(cache_dir=tmp_path)
    detail = {
        "scheme_code": "122639",
        "scheme_name": "Test Flexi",
        "fund_house": "Test AMC",
        "fund_manager": "A B",
        "expense_ratio": 0.7,
        "aum": 12000.5,
        "category": "Equity",
        "sub_category": "Flexi Cap",
        "holdings": [
            {
                "scheme_code": "122639",
                "portfolio_date": "2026-06-30",
                "company_name": "HDFC Bank Ltd",
                "nature_name": "EQUITY",
                "sector_name": "Financial",
                "instrument_name": "Equity",
                "corpus_per": 8.33,
                "market_cap": "Large Cap",
            },
            {
                "company_name": "TREPS",
                "nature_name": "CASH",
                "sector_name": "Cash",
                "corpus_per": 5.0,
            },
            {
                "company_name": "Microsoft Corporation",
                "nature_name": "EQUITY",
                "sector_name": "IT",
                "corpus_per": 4.2,
                "instrument_name": "International Equity",
            },
        ],
    }
    bundle = client._normalize_bundle(detail, "122639", source="groww")
    df = bundle["holdings"]
    assert len(df) == 3
    assert "HDFC Bank Ltd" in df["security_name"].values
    assert abs(df.loc[df["security_name"] == "HDFC Bank Ltd", "weight_pct"].iloc[0] - 8.33) < 1e-6
    assert bundle["meta"]["expense_ratio"] == 0.7
    assert bundle["meta"]["fund_manager"] == "A B"
    # TREPS → Cash asset type
    cash_rows = df[df["security_name"] == "TREPS"]
    assert cash_rows.iloc[0]["asset_type"] == "Cash"


def test_parse_array_holdings(tmp_path: Path) -> None:
    client = HoldingsClient(cache_dir=tmp_path)
    # v1 array form
    holdings = [
        ["122639", "2026-06-30", "Infosys", "EQUITY", "IT", "Equity", None, "1000", "6.5", None, None, "infosys"],
    ]
    df = client._parse_holdings(holdings)
    assert len(df) == 1
    assert df.iloc[0]["security_name"] == "Infosys"
    assert float(df.iloc[0]["weight_pct"]) == 6.5


def test_live_groww_optional() -> None:
    import pytest

    client = HoldingsClient()
    try:
        bundle = client.get_scheme_bundle(
            "122639",
            "Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
            force_refresh=True,
        )
    except Exception as exc:
        pytest.skip(f"Live Groww unavailable: {exc}")
    assert not bundle["holdings"].empty
    assert bundle["meta"].get("expense_ratio") is not None or bundle["meta"].get("aum_cr") is not None
