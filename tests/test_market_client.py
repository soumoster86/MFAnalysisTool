"""NSE / BSE market client — offline behaviour, caching and matching.

No test here touches the network: the exchanges are rate-limited and block
programmatic access without warning, so a suite that called them would fail for
reasons unrelated to the code.
"""

from __future__ import annotations


import pandas as pd
import pytest

from services.data.market_client import (
    MarketClient,
    _as_float,
    _normalise_company,
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Block both exchanges for every test in this module.

    Without this a test that forgets to seed the cache silently reaches the
    live API, which is slow, rate-limited and makes the suite fail for reasons
    that have nothing to do with the code.
    """

    def blocked(self, *args, **kwargs):
        raise RuntimeError("network disabled in tests")

    monkeypatch.setattr(MarketClient, "_nse_session", blocked)
    monkeypatch.setattr(MarketClient, "_bse_session", blocked)


@pytest.fixture()
def client(tmp_path) -> MarketClient:
    return MarketClient(cache_dir=tmp_path)


def _seed(client: MarketClient, key: str, payload) -> None:
    client._write_cache(key, payload)


INDEX_ROWS = [
    {"index": "NIFTY 50", "last": 24250.2, "pct_change": 1.1},
    {"index": "NIFTY BANK", "last": 57205.9, "pct_change": 0.79},
]

EQUITY_ROWS = [
    {"scrip_code": 500180, "name": "HDFC Bank Ltd", "symbol": "HDFCBANK", "last": 748.25,
     "pct_change": 1.74},
    {"scrip_code": 500209, "name": "Infosys Ltd", "symbol": "INFY", "last": 1155.5,
     "pct_change": 4.5},
]


# ------------------------------------------------------------------ normalise
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HDFC Bank Ltd", "hdfc bank"),
        ("HDFC Bank Limited", "hdfc bank"),
        ("Infosys Ltd.", "infosys"),
        ("Reliance Industries Ltd", "reliance industries"),
        ("Tata Consultancy Services Ltd.", "tata consultancy services"),
    ],
)
def test_company_names_normalise_to_a_common_key(raw, expected):
    assert _normalise_company(raw) == expected


def test_normalise_handles_empty_and_none():
    assert _normalise_company("") == ""
    assert _normalise_company(None) == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1,234.50", 1234.5), ("+8.10", 8.1), ("-0.64", -0.64), ("", None), (None, None),
     ("n/a", None)],
)
def test_numeric_parsing_tolerates_exchange_formatting(raw, expected):
    assert _as_float(raw) == expected


# --------------------------------------------------------------------- cache
def test_indices_are_served_from_cache_without_network(client):
    _seed(client, "nse_indices", INDEX_ROWS)
    df = client.get_indices()
    assert len(df) == 2
    assert set(df["index"]) == {"NIFTY 50", "NIFTY BANK"}


def test_index_lookup_is_case_insensitive_and_alias_aware(client):
    _seed(client, "nse_indices", INDEX_ROWS)
    assert client.get_index("nifty 50")["last"] == 24250.2
    assert client.get_index("BANKNIFTY")["index"] == "NIFTY BANK"
    assert client.get_index("NIFTY")["index"] == "NIFTY 50"


def test_unknown_index_returns_none(client):
    _seed(client, "nse_indices", INDEX_ROWS)
    assert client.get_index("NASDAQ 100") is None


def test_no_cache_and_no_network_returns_empty_frame_not_an_error(client):
    df = client.get_indices()
    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_stale_cache_is_served_when_the_exchange_blocks(client):
    # A blocked exchange must not blank the board — last known values are far
    # more useful than nothing.
    _seed(client, "nse_indices", INDEX_ROWS)
    path = client._cache_path("nse_indices")
    import os
    import time

    old = time.time() - 60 * 60 * 24
    os.utime(path, (old, old))

    df = client.get_indices()
    assert len(df) == 2


def test_corrupt_cache_does_not_crash(client):
    client._cache_path("nse_indices").write_text("{not json", encoding="utf-8")
    assert client.get_indices().empty


# ------------------------------------------------------------------- quotes
def test_equity_quote_matches_on_normalised_name(client):
    _seed(client, "bse_equities", EQUITY_ROWS)
    quote = client.get_equity_quote("HDFC Bank Limited")
    assert quote["scrip_code"] == 500180
    assert quote["last"] == 748.25


def test_equity_quote_for_an_unlisted_name_is_none(client):
    _seed(client, "bse_equities", EQUITY_ROWS)
    assert client.get_equity_quote("Some Unlisted Private Co") is None


def test_equity_quote_of_blank_is_none(client):
    _seed(client, "bse_equities", EQUITY_ROWS)
    assert client.get_equity_quote("") is None


# --------------------------------------------------------------- enrichment
def test_enrich_attaches_live_prices_to_matched_holdings(client):
    _seed(client, "bse_equities", EQUITY_ROWS)
    holdings = pd.DataFrame(
        [
            {"security_name": "HDFC Bank Ltd", "weight_pct": 8.0},
            {"security_name": "Infosys Ltd", "weight_pct": 6.0},
        ]
    )
    out, matched = client.enrich_holdings(holdings)
    assert matched == 2
    assert out.loc[0, "last_price"] == 748.25
    assert out.loc[1, "day_change_pct"] == 4.5


def test_unmatched_holdings_get_no_price_rather_than_a_wrong_one(client):
    # Showing an unmatched security with someone else's quote would be worse
    # than showing nothing.
    _seed(client, "bse_equities", EQUITY_ROWS)
    holdings = pd.DataFrame([{"security_name": "Unlisted Pvt Co", "weight_pct": 5.0}])
    out, matched = client.enrich_holdings(holdings)
    assert matched == 0
    assert pd.isna(out.loc[0, "last_price"])


def test_enrich_returns_input_unchanged_when_no_market_data(client):
    holdings = pd.DataFrame([{"security_name": "HDFC Bank Ltd", "weight_pct": 8.0}])
    out, matched = client.enrich_holdings(holdings)
    assert matched == 0
    assert len(out) == 1


def test_enrich_handles_empty_and_malformed_frames(client):
    _seed(client, "bse_equities", EQUITY_ROWS)
    empty, matched = client.enrich_holdings(pd.DataFrame())
    assert matched == 0
    no_col, matched2 = client.enrich_holdings(pd.DataFrame([{"other": 1}]))
    assert matched2 == 0


def test_enrich_respects_the_row_limit(client):
    _seed(client, "bse_equities", EQUITY_ROWS)
    holdings = pd.DataFrame(
        [{"security_name": "HDFC Bank Ltd", "weight_pct": 1.0} for _ in range(5)]
    )
    out, matched = client.enrich_holdings(holdings, limit=2)
    assert matched == 2
    assert pd.isna(out.loc[4, "last_price"])
