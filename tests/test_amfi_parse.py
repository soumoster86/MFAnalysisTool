"""Tests for AMFI text parsing (offline sample)."""

from services.data.amfi_client import AMFIClient

SAMPLE = """
ABC Mutual Fund
Scheme Code;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
120503;INF123;INF456;ABC Flexi Cap Fund - Direct Plan - Growth;85.4321;28-Mar-2025
Not a scheme line
120504;-;-;ABC Flexi Cap Fund - Regular Plan - Growth;80.12;28-Mar-2025
"""


def test_parse_nav_text() -> None:
    client = AMFIClient()
    df = client.parse_nav_text(SAMPLE)
    assert len(df) == 2
    assert "120503" in df["amfi_code"].astype(str).values
    assert df.loc[df["amfi_code"].astype(str) == "120503", "nav"].iloc[0] == 85.4321
    assert df["category"].notna().all()
