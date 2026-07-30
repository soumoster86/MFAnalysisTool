"""Screener scoring, persistence and ranking."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest


@pytest.fixture()
def isolated_db(tmp_path):
    db_path = tmp_path / "test_screener.db"
    url = f"sqlite:///{db_path.as_posix()}"

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from database import session as session_mod

    engine = create_engine(url, connect_args={"check_same_thread": False})
    session_mod.engine = engine
    session_mod.SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    import models  # noqa: F401

    session_mod.Base.metadata.drop_all(bind=engine)
    session_mod.Base.metadata.create_all(bind=engine)
    yield url


def _nav(
    points: int, annual_return: float = 0.12, seed: int = 1, vol: float = 0.008
) -> pd.Series:
    idx = pd.date_range(end=datetime(2026, 6, 30), periods=points, freq="B")
    rng = np.random.default_rng(seed)
    daily = annual_return / 252
    rets = rng.normal(daily, vol, size=points)
    nav = [100.0]
    for r in rets[1:]:
        nav.append(nav[-1] * (1 + r))
    return pd.Series(nav, index=idx)


# Equity funds are volatile with higher return; liquid funds are neither. The
# fixture mirrors that so cross-category ranking is exercised on realistically
# incomparable series.
CATEGORY_SHAPE = {
    "1": {"ret": 0.14, "vol": 0.009},  # 1xx = Flexi Cap
    "2": {"ret": 0.065, "vol": 0.0004},  # 2xx = Liquid
}


class _FakeFundService:
    """Serves a fixed universe with controllable NAV length and source."""

    def __init__(self, schemes, nav_points=1250, nav_source="mfapi", per_code=None):
        self._schemes = pd.DataFrame(schemes)
        self._nav_points = nav_points
        self._nav_source = nav_source
        self._per_code = per_code or {}
        self.amfi = self
        self.yf = self

    # amfi
    def load(self, force_refresh: bool = False):
        return self._schemes.copy()

    # yf
    def get_benchmark(self, name, period="5y"):
        return _nav(1250, 0.10, seed=99)

    def get_nav_history(self, code, scheme_name=None, latest_nav=None, years=5.0, **kw):
        cfg = self._per_code.get(str(code), {})
        shape = CATEGORY_SHAPE.get(str(code)[0], {"ret": 0.12, "vol": 0.008})
        # Seed on the full code so no two funds get an identical series — ties
        # would otherwise mask what the ranking tests are checking.
        return _nav(
            cfg.get("points", self._nav_points),
            cfg.get("ret", shape["ret"]),
            seed=int(code),
            vol=cfg.get("vol", shape["vol"]),
        )

    def get_nav_source(self, code):
        return self._per_code.get(str(code), {}).get("source", self._nav_source)

    @staticmethod
    def _fallback_expense(code):
        return 1.0

    @staticmethod
    def _fallback_aum(code):
        return 5000.0


SCHEMES = [
    {"amfi_code": "101", "scheme_name": "Alpha Flexi Cap - Direct Growth", "amc": "Alpha",
     "category": "Equity", "subcategory": "Flexi Cap", "is_direct": True, "is_growth": True,
     "nav": 100.0},
    {"amfi_code": "102", "scheme_name": "Beta Flexi Cap - Direct Growth", "amc": "Beta",
     "category": "Equity", "subcategory": "Flexi Cap", "is_direct": True, "is_growth": True,
     "nav": 100.0},
    {"amfi_code": "103", "scheme_name": "Gamma Flexi Cap - Direct Growth", "amc": "Gamma",
     "category": "Equity", "subcategory": "Flexi Cap", "is_direct": True, "is_growth": True,
     "nav": 100.0},
    {"amfi_code": "201", "scheme_name": "Alpha Liquid - Direct Growth", "amc": "Alpha",
     "category": "Debt", "subcategory": "Liquid", "is_direct": True, "is_growth": True,
     "nav": 100.0},
    {"amfi_code": "202", "scheme_name": "Beta Liquid - Direct Growth", "amc": "Beta",
     "category": "Debt", "subcategory": "Liquid", "is_direct": True, "is_growth": True,
     "nav": 100.0},
    {"amfi_code": "203", "scheme_name": "Gamma Liquid - Direct Growth", "amc": "Gamma",
     "category": "Debt", "subcategory": "Liquid", "is_direct": True, "is_growth": True,
     "nav": 100.0},
    {"amfi_code": "301", "scheme_name": "Alpha Flexi Cap - Regular IDCW", "amc": "Alpha",
     "category": "Equity", "subcategory": "Flexi Cap", "is_direct": False, "is_growth": False,
     "nav": 100.0},
]


def _service(isolated_db, **kw):
    from services.screener.screener_service import ScreenerService

    return ScreenerService(fund_service=_FakeFundService(SCHEMES, **kw))


# ------------------------------------------------------------------ universe
def test_universe_is_direct_growth_only(isolated_db):
    svc = _service(isolated_db)
    codes = set(svc.universe()["amfi_code"])
    # The Regular IDCW plan holds the same portfolio at a different TER and a
    # NAV that drops on payout — it would duplicate its Direct Growth sibling.
    assert "301" not in codes
    assert {"101", "201"} <= codes


def test_universe_filters_by_subcategory(isolated_db):
    svc = _service(isolated_db)
    assert set(svc.universe(subcategory="Liquid")["amfi_code"]) == {"201", "202", "203"}


def test_categories_lists_subcategories(isolated_db):
    assert _service(isolated_db).categories() == ["Flexi Cap", "Liquid"]


# ------------------------------------------------------------------- scoring
def test_scoring_persists_and_is_reloadable(isolated_db):
    svc = _service(isolated_db)
    run = svc.score_universe(limit=10)
    assert run.scored == 6
    assert run.failed == 0
    df = svc.load_scores(min_years=0)
    assert len(df) == 6
    assert df["overall"].notna().all()


def test_scores_carry_metrics_and_provenance(isolated_db):
    svc = _service(isolated_db)
    svc.score_universe(limit=10)
    row = svc.load_scores(min_years=0).iloc[0]
    assert row["nav_source"] == "mfapi"
    assert row["nav_points"] > 0
    assert row["years_covered"] > 0
    assert row["cagr"] is not None


def test_rerunning_does_not_duplicate_rows(isolated_db):
    svc = _service(isolated_db)
    svc.score_universe(limit=10)
    svc.score_universe(limit=10)  # already scored — nothing new
    assert len(svc.load_scores(min_years=0)) == 6


def test_rescore_updates_in_place(isolated_db):
    svc = _service(isolated_db)
    svc.score_universe(limit=10)
    before = svc.load_scores(min_years=0)
    run = svc.score_universe(limit=10, rescore=True)
    after = svc.load_scores(min_years=0)
    assert run.scored == 6
    assert len(after) == len(before) == 6


def test_second_run_skips_already_scored_funds(isolated_db):
    svc = _service(isolated_db)
    svc.score_universe(limit=3)
    run = svc.score_universe(limit=10)
    # Three were already done, so only the remaining three get scored.
    assert run.scored == 3


# ------------------------------------------------- data-quality exclusions
def test_synthetic_nav_funds_are_never_scored(isolated_db):
    svc = _service(isolated_db, per_code={"101": {"source": "synthetic"}})
    run = svc.score_universe(limit=10)
    assert run.skipped_fabricated == 1
    assert "101" not in set(svc.load_scores(min_years=0)["amfi_code"])


def test_short_history_funds_are_not_stored(isolated_db):
    svc = _service(isolated_db, per_code={"101": {"points": 60}})
    run = svc.score_universe(limit=10)
    assert run.skipped_short_history == 1
    assert "101" not in set(svc.load_scores(min_years=0)["amfi_code"])


def test_min_years_filter_excludes_young_funds_from_rankings(isolated_db):
    # ~300 business days is over a year, so it is stored, but under three.
    svc = _service(isolated_db, per_code={"101": {"points": 300}})
    svc.score_universe(limit=10)
    assert "101" in set(svc.load_scores(min_years=0)["amfi_code"])
    assert "101" not in set(svc.load_scores(min_years=3)["amfi_code"])


def test_ranks_are_computed_after_filtering(isolated_db):
    # An excluded fund must not occupy a rank position, so ranks stay inside
    # the surviving set. Equal scores legitimately share a rank (competition
    # ranking), so contiguity is not the property being asserted here.
    svc = _service(isolated_db, per_code={"101": {"points": 300}})
    svc.score_universe(limit=10)
    df = svc.load_scores(min_years=3)
    assert df["overall_rank"].min() == 1
    assert df["overall_rank"].max() <= len(df)


# ------------------------------------------------------------------ ranking
def test_raw_ranking_is_ordered_by_score(isolated_db):
    svc = _service(isolated_db)
    svc.score_universe(limit=10)
    df = svc.overall_ranking(10, scores=svc.load_scores(min_years=0), peer_relative=False)
    assert list(df["overall"]) == sorted(df["overall"], reverse=True)
    assert df.iloc[0]["overall_rank"] == 1


def test_peer_relative_is_the_default_board(isolated_db):
    # Raw score is not comparable across categories, so the default must not be
    # a raw-score board.
    svc = _service(isolated_db)
    svc.score_universe(limit=10)
    scores = svc.load_scores(min_years=0)
    default = svc.overall_ranking(10, scores=scores)
    peer = svc.overall_ranking(10, scores=scores, peer_relative=True)
    assert list(default["amfi_code"]) == list(peer["amfi_code"])


def test_peer_relative_board_is_ordered_by_percentile(isolated_db):
    svc = _service(isolated_db)
    svc.score_universe(limit=10)
    df = svc.overall_ranking(10, scores=svc.load_scores(min_years=0))
    pct = list(df["category_percentile"])
    assert pct == sorted(pct, reverse=True)


def test_overall_ranking_respects_the_limit(isolated_db):
    svc = _service(isolated_db)
    svc.score_universe(limit=10)
    assert len(svc.overall_ranking(3, scores=svc.load_scores(min_years=0))) == 3


def test_category_rank_is_relative_to_peers_not_the_whole_universe(isolated_db):
    svc = _service(isolated_db)
    svc.score_universe(limit=10)
    df = svc.load_scores(min_years=0)
    for _, group in df.groupby("subcategory"):
        # Every category restarts at 1 and never exceeds its own size — that is
        # what makes it a peer rank rather than a slice of the global one.
        assert group["category_rank"].min() == 1
        assert group["category_rank"].max() <= len(group)


def test_top_by_category_returns_each_category_ranked(isolated_db):
    svc = _service(isolated_db)
    svc.score_universe(limit=10)
    groups = svc.top_by_category(10, scores=svc.load_scores(min_years=0))
    assert set(groups) == {"Flexi Cap", "Liquid"}
    for group in groups.values():
        assert list(group["overall"]) == sorted(group["overall"], reverse=True)


def test_top_by_category_caps_at_n(isolated_db):
    svc = _service(isolated_db)
    svc.score_universe(limit=10)
    groups = svc.top_by_category(2, scores=svc.load_scores(min_years=0))
    assert all(len(g) <= 2 for g in groups.values())


def test_thin_categories_are_hidden(isolated_db):
    # A league table of one or two funds is noise dressed up as a ranking.
    svc = _service(isolated_db)
    svc.score_universe(limit=10)
    groups = svc.top_by_category(10, min_funds=4, scores=svc.load_scores(min_years=0))
    assert groups == {}


# ----------------------------------------------------------------- coverage
def test_coverage_reports_universe_scored_and_exclusions(isolated_db):
    svc = _service(
        isolated_db,
        per_code={"101": {"source": "synthetic"}, "102": {"points": 300}},
    )
    svc.score_universe(limit=10)
    cov = svc.coverage(min_years=3)
    assert cov["universe"] == 6
    assert cov["excluded_short_history"] == 1
    assert cov["rankable"] == 4
    assert cov["categories"] == 2


# --------------------------------------------------- data-quality guards
def test_nav_rebasing_is_not_treated_as_a_return():
    # Real AMFI cases: a +900% day on an overnight fund, +169% on a wound-down
    # debt fund. Both are unit rebasings that poison CAGR and volatility.
    from services.screener.screener_service import nav_discontinuity

    nav = _nav(600, 0.08, seed=5)
    assert nav_discontinuity(nav) is None

    nav.iloc[300] = nav.iloc[300] * 10
    hit = nav_discontinuity(nav)
    assert hit is not None
    when, move = hit
    assert move > 1.0


def test_fund_with_a_rebased_nav_is_excluded_from_scoring(isolated_db):
    from services.screener.screener_service import ScreenerService

    class _Rebased(_FakeFundService):
        def get_nav_history(self, code, scheme_name=None, latest_nav=None, years=5.0, **kw):
            nav = super().get_nav_history(code, scheme_name, latest_nav, years, **kw)
            if str(code) == "101":
                nav.iloc[500] = nav.iloc[500] * 10
            return nav

    svc = ScreenerService(fund_service=_Rebased(SCHEMES))
    run = svc.score_universe(limit=10)
    assert run.skipped_discontinuity == 1
    assert "101" not in set(svc.load_scores(min_years=0)["amfi_code"])


@pytest.mark.parametrize(
    "name",
    [
        "JM Liquid Fund - Unclaimed Brokerage I.E.F. (Direct) - Growth Plan",
        "Some Fund Segregated Portfolio 1 - Direct Growth",
        "ABC Fund Side Pocket - Direct Growth",
    ],
)
def test_administrative_plans_are_not_investable(name):
    from services.screener.screener_service import is_investable

    assert not is_investable(name)


def test_ordinary_schemes_remain_investable():
    from services.screener.screener_service import is_investable

    assert is_investable("HDFC Flexi Cap Fund - Direct Plan - Growth")
    assert is_investable("ICICI Prudential Overnight Fund - Direct Plan - Growth")


def test_universe_excludes_administrative_plans(isolated_db):
    from services.screener.screener_service import ScreenerService

    rows = SCHEMES + [
        {
            "amfi_code": "999",
            "scheme_name": "JM Liquid Fund - Unclaimed Redemption IEF (Direct) Growth Plan",
            "amc": "JM", "category": "Debt", "subcategory": "Liquid",
            "is_direct": True, "is_growth": True, "nav": 100.0,
        }
    ]
    svc = ScreenerService(fund_service=_FakeFundService(rows))
    assert "999" not in set(svc.universe()["amfi_code"])


def test_near_zero_volatility_yields_no_sharpe():
    # An overnight fund at 0.12% annualised volatility turned a few basis
    # points of shortfall into a Sharpe of -16, which reads as catastrophic
    # and means nothing.
    from analytics.risk_metrics import RiskMetricsCalculator

    calc = RiskMetricsCalculator()
    flat = _nav(600, 0.055, seed=11, vol=0.00003)
    returns = calc.nav_to_returns(flat)
    assert calc.annualized_vol(returns) < 0.005
    assert calc.sharpe_ratio(returns) is None
    assert calc.sortino_ratio(returns) is None


def test_normal_volatility_still_yields_a_sharpe():
    from analytics.risk_metrics import RiskMetricsCalculator

    calc = RiskMetricsCalculator()
    returns = calc.nav_to_returns(_nav(600, 0.14, seed=12, vol=0.009))
    assert calc.sharpe_ratio(returns) is not None


# ------------------------------------------------------- peer-relative rank
def test_peer_relative_ranking_does_not_favour_one_category(isolated_db):
    # A raw board lets low-volatility categories sweep the top; ranking on
    # percentile-within-category must surface leaders from both.
    svc = _service(isolated_db)
    svc.score_universe(limit=10)
    scores = svc.load_scores(min_years=0)
    board = svc.overall_ranking(2, scores=scores, peer_relative=True)
    assert set(board["subcategory"]) == {"Flexi Cap", "Liquid"}


def test_peer_relative_top_funds_lead_their_own_category(isolated_db):
    svc = _service(isolated_db)
    svc.score_universe(limit=10)
    board = svc.overall_ranking(2, scores=svc.load_scores(min_years=0), peer_relative=True)
    assert set(board["category_rank"]) == {1}


def test_raw_ranking_still_available(isolated_db):
    svc = _service(isolated_db)
    svc.score_universe(limit=10)
    board = svc.overall_ranking(6, scores=svc.load_scores(min_years=0), peer_relative=False)
    assert list(board["overall"]) == sorted(board["overall"], reverse=True)


def test_unclassified_is_not_treated_as_a_peer_group(isolated_db):
    # AMFI leaves ~a third of schemes uncategorised; the bucket holds
    # medium-duration debt beside innovation equity, so it is not a peer set.
    from services.screener.screener_service import ScreenerService, is_peer_group

    assert not is_peer_group("Unclassified")
    assert is_peer_group("Flexi Cap")

    rows = SCHEMES + [
        {
            "amfi_code": f"4{i:02d}",
            "scheme_name": f"Misc Fund {i} - Direct Growth",
            "amc": "Misc", "category": "Other", "subcategory": "Unclassified",
            "is_direct": True, "is_growth": True, "nav": 100.0,
        }
        for i in range(4)
    ]
    svc = ScreenerService(fund_service=_FakeFundService(rows))
    svc.score_universe(limit=20)
    df = svc.load_scores(min_years=0)

    assert df[df["subcategory"] == "Unclassified"]["category_percentile"].isna().all()
    assert "Unclassified" not in svc.top_by_category(10, scores=df)
    board = svc.overall_ranking(20, scores=df, peer_relative=True)
    assert "Unclassified" not in set(board["subcategory"])


def test_percentile_is_withheld_for_categories_too_thin_to_rank(isolated_db):
    from services.screener.screener_service import ScreenerService

    rows = [r for r in SCHEMES if r["amfi_code"] in {"101", "102", "103", "201"}]
    svc = ScreenerService(fund_service=_FakeFundService(rows))
    svc.score_universe(limit=10)
    df = svc.load_scores(min_years=0)
    # Liquid has one fund — a percentile from a peer group of one is arithmetic.
    assert df[df["subcategory"] == "Liquid"]["category_percentile"].isna().all()
    assert df[df["subcategory"] == "Flexi Cap"]["category_percentile"].notna().all()


def test_empty_database_reads_are_safe(isolated_db):
    svc = _service(isolated_db)
    assert svc.load_scores().empty
    assert svc.top_by_category(10) == {}
    assert svc.overall_ranking(10).empty
    assert svc.coverage()["scored"] == 0
