"""IDCW / dividend history: provider parsing and NAV-divergence derivation."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from services.data.dividends import (
    find_growth_sibling,
    Dividend,
    derive_from_navs,
    from_provider,
    growth_sibling_name,
    is_idcw_plan,
)


def _pair(days: int = 120, payouts: dict[int, float] | None = None):
    """Growth and IDCW NAV series over the same portfolio.

    The IDCW plan tracks Growth exactly, except on payout days where its NAV
    drops by the distributed amount — which is what a real distribution does.
    """
    idx = pd.date_range(end=datetime(2026, 6, 30), periods=days, freq="B")
    rng = np.random.default_rng(7)
    rets = rng.normal(0.0004, 0.006, size=days)

    growth = [100.0]
    for r in rets[1:]:
        growth.append(growth[-1] * (1 + r))

    idcw = [100.0]
    payouts = payouts or {}
    for i, r in enumerate(rets[1:], start=1):
        nav = idcw[-1] * (1 + r)
        if i in payouts:
            nav -= payouts[i]
        idcw.append(nav)

    return pd.Series(growth, index=idx), pd.Series(idcw, index=idx)


# ------------------------------------------------------------ plan detection
@pytest.mark.parametrize(
    "name",
    [
        "HDFC Flexi Cap Fund - Direct Plan - IDCW",
        "SBI Bluechip Fund - Regular - Dividend Payout",
        "Axis Fund Income Distribution cum capital withdrawal",
    ],
)
def test_payout_plans_are_recognised(name):
    assert is_idcw_plan(name)


@pytest.mark.parametrize(
    "name",
    [
        "HDFC Flexi Cap Fund - Direct Plan - Growth",
        "SBI Bluechip Fund - Direct Growth",
    ],
)
def test_growth_plans_are_not_payout_plans(name):
    assert not is_idcw_plan(name)


def test_growth_sibling_name_swaps_the_plan_wording():
    assert (
        growth_sibling_name("HDFC Flexi Cap Fund - Direct Plan - IDCW")
        == "HDFC Flexi Cap Fund - Direct Plan - Growth"
    )


# ------------------------------------------------------------ sibling match
class _FakeFundService:
    def __init__(self, rows):
        self._rows = rows

    def search_funds(self, query, limit=25):
        q = query.strip().lower()
        return pd.DataFrame(
            [r for r in self._rows if q in str(r["scheme_name"]).lower()]
        )


# Real AMFI names: irregular spacing, inconsistent plan wording.
AMFI_ROWS = [
    {"amfi_code": "119550", "scheme_name": "Aditya Birla Sun Life Banking & PSU Debt Fund- Direct Plan-Growth"},
    {"amfi_code": "119551", "scheme_name": "Aditya Birla Sun Life Banking & PSU Debt Fund  - DIRECT - IDCW"},
    {"amfi_code": "119548", "scheme_name": "Aditya Birla Sun Life Banking & PSU Debt Fund - REGULAR PLAN - Growth"},
    {"amfi_code": "100001", "scheme_name": "HDFC Flexi Cap Fund - Direct Plan - Growth"},
]


def test_sibling_matches_despite_irregular_spacing_and_wording():
    # The IDCW name has double spaces and "DIRECT"; the Growth name has none
    # and "Direct Plan". A reconstructed-name substring search finds nothing.
    svc = _FakeFundService(AMFI_ROWS)
    sib = find_growth_sibling(
        svc, "Aditya Birla Sun Life Banking & PSU Debt Fund  - DIRECT - IDCW", "119551"
    )
    assert sib is not None
    assert sib["amfi_code"] == "119550"


def test_sibling_must_share_the_direct_or_regular_plan_type():
    # Direct vs Regular differ by TER and would drift apart for reasons that
    # are not distributions, so the Regular Growth plan must not be chosen.
    svc = _FakeFundService([r for r in AMFI_ROWS if r["amfi_code"] != "119550"])
    sib = find_growth_sibling(
        svc, "Aditya Birla Sun Life Banking & PSU Debt Fund  - DIRECT - IDCW", "119551"
    )
    assert sib is None


def test_sibling_of_a_different_fund_is_not_matched():
    svc = _FakeFundService(AMFI_ROWS)
    sib = find_growth_sibling(svc, "HDFC Flexi Cap Fund - Direct Plan - IDCW", "999")
    assert sib is not None
    assert sib["amfi_code"] == "100001"


def test_frequency_wording_does_not_prevent_a_match():
    svc = _FakeFundService(AMFI_ROWS)
    sib = find_growth_sibling(
        svc,
        "Aditya Birla Sun Life Banking & PSU Debt Fund  - Direct - Quarterly IDCW",
        "119553",
    )
    assert sib is not None
    assert sib["amfi_code"] == "119550"


def test_no_candidates_returns_none():
    assert find_growth_sibling(_FakeFundService([]), "Some Fund - IDCW", "1") is None


# ------------------------------------------------------------------ derived
def test_no_payouts_means_no_dividends_detected():
    growth, idcw = _pair()
    assert derive_from_navs(idcw, growth) == []


def test_a_payout_is_detected_on_the_right_day_with_the_right_amount():
    growth, idcw = _pair(payouts={60: 5.0})
    found = derive_from_navs(idcw, growth)
    assert len(found) == 1
    # ~5 rupees off a NAV near 100.
    assert found[0].amount_per_unit == pytest.approx(5.0, rel=0.05)
    assert found[0].source == "derived"
    assert found[0].nav_before is not None


def test_multiple_payouts_are_all_detected_newest_first():
    growth, idcw = _pair(payouts={40: 3.0, 80: 4.0})
    found = derive_from_navs(idcw, growth)
    assert len(found) == 2
    assert found[0].record_date > found[1].record_date


def test_ordinary_daily_noise_is_not_mistaken_for_a_payout():
    # The plans diverge slightly through rounding; that must not fire.
    growth, idcw = _pair()
    noisy = idcw * (1 + np.random.default_rng(3).normal(0, 0.0005, size=len(idcw)))
    assert derive_from_navs(noisy, growth) == []


def test_larger_payouts_carry_higher_confidence():
    _, small = _pair(payouts={60: 0.8})
    growth, big = _pair(payouts={60: 8.0})
    small_hit = derive_from_navs(small, growth)
    big_hit = derive_from_navs(big, growth)
    assert small_hit and big_hit
    assert big_hit[0].confidence > small_hit[0].confidence


def test_implausible_divergence_is_rejected_as_a_mismatched_sibling():
    # Comparing against an unrelated fund would invent payouts; a >60% one-day
    # gap means the series are not the same portfolio.
    growth, idcw = _pair()
    broken = idcw.copy()
    broken.iloc[60] = broken.iloc[60] * 0.2
    assert derive_from_navs(broken, growth) == []


def test_empty_or_short_series_return_nothing():
    growth, idcw = _pair()
    assert derive_from_navs(pd.Series(dtype=float), growth) == []
    assert derive_from_navs(idcw, pd.Series(dtype=float)) == []
    assert derive_from_navs(idcw.head(3), growth.head(3)) == []


def test_non_overlapping_dates_return_nothing():
    growth, idcw = _pair()
    shifted = idcw.copy()
    shifted.index = shifted.index + pd.Timedelta(days=4000)
    assert derive_from_navs(shifted, growth) == []


# ----------------------------------------------------------------- provider
def test_provider_rows_are_parsed_and_marked_authoritative():
    detail = {
        "dividend": [
            {"record_date": "15-03-2026", "dividend": "2.50", "type": "IDCW"},
            {"record_date": "12-09-2025", "dividend": 1.75},
        ]
    }
    rows = from_provider(detail)
    assert len(rows) == 2
    assert all(r.source == "provider" for r in rows)
    assert all(r.confidence == 1.0 for r in rows)
    assert rows[0].record_date > rows[1].record_date


def test_provider_absent_or_empty_yields_nothing():
    assert from_provider(None) == []
    assert from_provider({}) == []
    assert from_provider({"dividend": None}) == []
    assert from_provider({"dividend": []}) == []


def test_malformed_provider_rows_are_skipped_not_fatal():
    detail = {
        "dividend": [
            {"record_date": "not a date", "dividend": "2.50"},
            {"dividend": "1.00"},
            {"record_date": "15-03-2026"},
            {"record_date": "15-03-2026", "dividend": "0"},
            "junk",
            {"record_date": "15-03-2026", "dividend": "2.50"},
        ]
    }
    rows = from_provider(detail)
    assert len(rows) == 1


def test_dividend_serialises_with_an_iso_date():
    d = Dividend(record_date=pd.Timestamp("2026-03-15").date(), amount_per_unit=2.5)
    assert d.to_dict()["record_date"] == "2026-03-15"
