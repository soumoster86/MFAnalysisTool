"""Tests for historical NAV client (offline parse + cache)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from services.data.mfapi_client import MFAPIClient


SAMPLE_MFAPI = {
    "meta": {
        "fund_house": "Test MF",
        "scheme_type": "Open Ended Schemes",
        "scheme_category": "Equity Scheme - Flexi Cap Fund",
        "scheme_code": 122639,
        "scheme_name": "Test Flexi Cap - Direct Growth",
        "isin_growth": "INF000",
        "isin_div_reinvestment": None,
    },
    "data": [
        {"date": "28-07-2026", "nav": "100.5"},
        {"date": "25-07-2026", "nav": "99.0"},
        {"date": "01-01-2024", "nav": "80.0"},
        {"date": "01-01-2020", "nav": "50.0"},
    ],
    "status": "SUCCESS",
}


def test_parse_mfapi_data(tmp_path: Path) -> None:
    client = MFAPIClient(cache_dir=tmp_path)
    s = client._parse_mfapi_data(SAMPLE_MFAPI, "122639")
    assert len(s) == 4
    assert float(s.iloc[-1]) == 100.5
    assert s.attrs["source"] == "mfapi"
    assert "Flexi" in str(s.name)


def test_cache_roundtrip(tmp_path: Path) -> None:
    client = MFAPIClient(cache_dir=tmp_path, cache_hours=24)
    s = client._parse_mfapi_data(SAMPLE_MFAPI, "122639")
    client.save_cache("122639", s)
    loaded = client.load_cached("122639")
    assert loaded is not None
    assert len(loaded) == 4
    assert abs(float(loaded.iloc[-1]) - 100.5) < 1e-9


def test_trim_years(tmp_path: Path) -> None:
    client = MFAPIClient(cache_dir=tmp_path)
    s = client._parse_mfapi_data(SAMPLE_MFAPI, "122639")
    trimmed = client._trim(s, years=1.0)
    assert len(trimmed) <= len(s)
    assert trimmed.index.max() == s.index.max()


def test_live_mfapi_optional() -> None:
    """Integration: skip if network blocked."""
    client = MFAPIClient()
    try:
        s = client.get_nav_history("122639", years=2.0, force_refresh=True)
    except Exception as exc:
        pytest.skip(f"Live mfapi unavailable: {exc}")
    assert len(s) > 100
    assert s.attrs.get("source") in ("mfapi", "tigzig", "disk_cache")
