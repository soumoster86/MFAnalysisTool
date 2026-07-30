"""Score and rank the fund universe (Screener).

There are ~2,500 Direct Growth schemes and scoring one means fetching its NAV
history, so scoring cannot happen inside a page render. Scores are computed in
bounded batches, persisted to `fund_scores`, and the page reads from that.

Two rules keep the rankings honest:

1. **A fund scored on a synthetic NAV path is excluded from rankings.** Ranking
   fabricated performance against real performance is worse than leaving the
   fund out — see services.data.provenance.
2. **Cross-category rank is reported alongside category rank, never instead of
   it.** A liquid fund and a small-cap fund are exposed to different risks, so
   their scores are not really commensurable. The overall board answers the
   question as asked, and the category rank column keeps the fairer comparison
   in view.

Screener scores are NAV-based: the stock-level holdings fetch is skipped
because it is the slow call. The two holdings factors are absent and scored
neutral by `FundHealthScorer`, so a screener score can differ slightly from the
Fund Health page's score for the same fund.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

import pandas as pd

from analytics.health_score import FundHealthScorer
from analytics.risk_metrics import RiskMetricsCalculator
from database import schema_repair
from database import session as db_session
from models.fund import FundScore
from services.data.provenance import FABRICATED, classify
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Roughly one year of trading days. Below this the risk metrics are too
# unstable to be worth storing at all.
MIN_NAV_POINTS = 250

# Default history required to appear in a ranking. A fund with seven months of
# data can post a flattering annualised CAGR off one good run, and placing that
# beside a five-year record invites exactly the wrong conclusion. Three years
# is the conventional bar for judging a fund; the UI can lower it.
DEFAULT_MIN_YEARS = 3.0

NAV_WORKERS = 8

# A mutual fund NAV does not move this far in one session. When it does, the
# series contains a unit rebasing or a segregated-portfolio restoration, not a
# return — real examples in the AMFI feed include a +900% day on an overnight
# fund and +169% on a wound-down debt fund. One such jump makes CAGR and
# volatility meaningless, so the fund is left out rather than ranked on it.
MAX_PLAUSIBLE_DAILY_MOVE = 0.25

# Administrative plans that are not investable products. They hold unclaimed
# balances or side-pocketed assets, carry flat or nonsensical NAVs, and have no
# business in a ranking of funds to buy.
NON_INVESTABLE_MARKERS = (
    "unclaimed",
    "i.e.f.",
    "ief",
    "segregated",
    "side pocket",
    "side-pocket",
)


def is_investable(scheme_name: str) -> bool:
    """False for administrative or side-pocketed plans."""
    lowered = f" {str(scheme_name or '').lower()} "
    return not any(marker in lowered for marker in NON_INVESTABLE_MARKERS)


def nav_discontinuity(nav: pd.Series) -> Optional[tuple[str, float]]:
    """The worst implausible one-day move, or None if the series is clean."""
    returns = nav.pct_change().dropna()
    if returns.empty:
        return None
    worst = returns.abs().idxmax()
    move = float(returns.loc[worst])
    if abs(move) > MAX_PLAUSIBLE_DAILY_MOVE:
        return str(pd.Timestamp(worst).date()), move
    return None

# Ranking a category with only one or two scored funds is noise dressed up as a
# league table.
MIN_FUNDS_PER_CATEGORY = 3

# AMFI's scheme names do not always yield a category, and the leftovers land
# here. It is not a peer group — the bucket holds medium-duration debt next to
# innovation equity — so it is never ranked as one.
UNCLASSIFIED = "Unclassified"


def is_peer_group(subcategory: Any) -> bool:
    """False for buckets that are not a comparable set of funds."""
    return str(subcategory or "").strip().lower() != UNCLASSIFIED.lower()


@dataclass
class ScoreRun:
    """Outcome of a batch scoring pass."""

    scored: int = 0
    skipped_short_history: int = 0
    skipped_fabricated: int = 0
    skipped_discontinuity: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "scored": self.scored,
            "skipped_short_history": self.skipped_short_history,
            "skipped_fabricated": self.skipped_fabricated,
            "skipped_discontinuity": self.skipped_discontinuity,
            "failed": self.failed,
            "errors": self.errors[:20],
            "elapsed_seconds": round(self.elapsed_seconds, 1),
        }


class ScreenerService:
    """Batch-score the fund universe and rank it."""

    _schema_checked = False

    def __init__(self, fund_service: Optional[Any] = None) -> None:
        if fund_service is None:
            from services.data.fund_service import FundService

            fund_service = FundService()
        self.funds = fund_service
        self.risk = RiskMetricsCalculator()
        self.scorer = FundHealthScorer()
        # Scoring thousands of funds must not trigger a DB write per NAV fetch.
        self.funds._bulk_skip_persist = True  # type: ignore[attr-defined]

    # ------------------------------------------------------------------- setup
    def ensure_db(self) -> None:
        try:
            db_session.init_db()
        except Exception as exc:
            logger.warning("init_db during screener ensure: {}", exc)
        if not ScreenerService._schema_checked:
            ScreenerService._schema_checked = True
            try:
                schema_repair.ensure_tables(FundScore.__table__, label="screener")
            except Exception as exc:
                logger.warning("Screener schema repair skipped: {}", exc)

    # ------------------------------------------------------------------ universe
    def universe(
        self,
        *,
        subcategory: Optional[str] = None,
        category: Optional[str] = None,
        direct_growth_only: bool = True,
    ) -> pd.DataFrame:
        """Investable scheme list: Direct Growth plans by default.

        Regular plans hold the same portfolio at a higher TER, and IDCW plans
        have a NAV that falls on payout, so including either would clutter the
        ranking with duplicates of the same fund.
        """
        df = self.funds.amfi.load()
        if df is None or df.empty:
            return pd.DataFrame()
        if direct_growth_only and {"is_direct", "is_growth"} <= set(df.columns):
            df = df[df["is_direct"] & df["is_growth"]]
        if category and category != "All":
            df = df[df["category"] == category]
        if subcategory and subcategory != "All":
            df = df[df["subcategory"] == subcategory]
        if "scheme_name" in df.columns:
            df = df[df["scheme_name"].apply(is_investable)]
        return df.reset_index(drop=True)

    def categories(self) -> list[str]:
        df = self.universe()
        if df.empty or "subcategory" not in df.columns:
            return []
        return sorted(str(c) for c in df["subcategory"].dropna().unique())

    # ------------------------------------------------------------------ scoring
    def score_fund(self, code: str, meta: dict[str, Any], benchmark: Any = None) -> Optional[dict[str, Any]]:
        """Score one fund from its NAV history. None if it cannot be ranked."""
        name = str(meta.get("scheme_name") or code)
        nav = self.funds.get_nav_history(code, name, meta.get("nav"), years=5.0)
        source = self.funds.get_nav_source(code)

        # A synthetic path would rank fabricated performance against real.
        if classify(source) == FABRICATED:
            return {"_skip": "fabricated", "amfi_code": code}

        clean = nav.dropna() if nav is not None else None
        if clean is None or len(clean) < MIN_NAV_POINTS:
            return {"_skip": "short_history", "amfi_code": code}

        jump = nav_discontinuity(clean)
        if jump is not None:
            when, move = jump
            logger.info(
                "Skipping {} ({}): NAV moved {:.0%} on {} — rebasing, not a return",
                code, name[:40], move, when,
            )
            return {"_skip": "discontinuity", "amfi_code": code}

        metrics = self.risk.compute(clean, benchmark)
        expense = meta.get("expense_ratio")
        if expense is None:
            expense = self.funds._fallback_expense(code)
        aum = meta.get("aum_cr")
        if aum is None:
            aum = self.funds._fallback_aum(code)

        health = self.scorer.score(
            cagr=metrics.cagr,
            sharpe=metrics.sharpe,
            sortino=metrics.sortino,
            max_drawdown=metrics.max_drawdown,
            volatility=metrics.volatility,
            alpha=metrics.alpha,
            beta=metrics.beta,
            information_ratio=metrics.information_ratio,
            expense_ratio=expense,
            aum_cr=aum,
            manager_tenure_years=meta.get("fund_manager_tenure_years"),
            # Holdings deliberately not fetched — see module docstring.
            top10_concentration=None,
            n_holdings=None,
        )

        span_days = (clean.index.max() - clean.index.min()).days if len(clean) > 1 else 0
        return {
            "amfi_code": str(code),
            "scheme_name": name[:512],
            "amc": (meta.get("amc") or None),
            "category": (meta.get("category") or None),
            "subcategory": (meta.get("subcategory") or None),
            "overall": health.overall,
            "growth": health.growth,
            "risk": health.risk,
            "quality": health.quality,
            "cost_efficiency": health.cost_efficiency,
            "consistency": health.consistency,
            "diversification": health.diversification,
            "cagr": metrics.cagr,
            "volatility": metrics.volatility,
            "sharpe": metrics.sharpe,
            "sortino": metrics.sortino,
            "max_drawdown": metrics.max_drawdown,
            "alpha": metrics.alpha,
            "beta": metrics.beta,
            "expense_ratio": float(expense) if expense is not None else None,
            "aum_cr": float(aum) if aum is not None else None,
            "nav_source": source,
            "nav_points": int(len(clean)),
            "years_covered": round(span_days / 365.25, 2) if span_days else None,
            "has_holdings": False,
        }

    def score_universe(
        self,
        *,
        limit: int = 200,
        subcategory: Optional[str] = None,
        category: Optional[str] = None,
        rescore: bool = False,
        progress: Optional[Callable[[float, str], None]] = None,
    ) -> ScoreRun:
        """Score up to `limit` unscored funds and persist the results."""
        self.ensure_db()
        run = ScoreRun()
        started = datetime.utcnow()

        pool = self.universe(subcategory=subcategory, category=category)
        if pool.empty:
            run.errors.append("No schemes in the selected universe.")
            return run

        if not rescore:
            already = self.scored_codes()
            pool = pool[~pool["amfi_code"].astype(str).isin(already)]
        pool = pool.head(limit)
        if pool.empty:
            return run

        try:
            benchmark = self.funds.yf.get_benchmark("NIFTY 50")
        except Exception as exc:
            logger.warning("Benchmark unavailable, alpha/beta will be absent: {}", exc)
            benchmark = None

        rows = pool.to_dict("records")
        total = len(rows)
        results: list[dict[str, Any]] = []

        def report(done: int) -> None:
            if progress:
                try:
                    progress(done / total, f"Scored {done}/{total}")
                except Exception:
                    pass

        with ThreadPoolExecutor(max_workers=NAV_WORKERS) as pool_exec:
            futures = {
                pool_exec.submit(self._safe_score, str(r["amfi_code"]), r, benchmark): r
                for r in rows
            }
            for i, future in enumerate(as_completed(futures), start=1):
                meta = futures[future]
                try:
                    out = future.result()
                except Exception as exc:
                    run.failed += 1
                    run.errors.append(f"{meta.get('amfi_code')}: {exc}")
                    report(i)
                    continue
                if out is None:
                    run.failed += 1
                elif out.get("_skip") == "fabricated":
                    run.skipped_fabricated += 1
                elif out.get("_skip") == "short_history":
                    run.skipped_short_history += 1
                elif out.get("_skip") == "discontinuity":
                    run.skipped_discontinuity += 1
                else:
                    results.append(out)
                report(i)

        if results:
            self._persist(results)
            run.scored = len(results)

        run.elapsed_seconds = (datetime.utcnow() - started).total_seconds()
        logger.info("Screener run: {}", run.to_dict())
        return run

    def _safe_score(
        self, code: str, meta: dict[str, Any], benchmark: Any
    ) -> Optional[dict[str, Any]]:
        try:
            return self.score_fund(code, meta, benchmark)
        except Exception as exc:
            logger.debug("Score failed for {}: {}", code, exc)
            return None

    def _persist(self, rows: list[dict[str, Any]]) -> None:
        """Upsert scores by amfi_code."""
        with db_session.SessionLocal() as db:
            try:
                existing = {
                    r.amfi_code: r
                    for r in db.query(FundScore)
                    .filter(FundScore.amfi_code.in_([r["amfi_code"] for r in rows]))
                    .all()
                }
                for row in rows:
                    target = existing.get(row["amfi_code"])
                    if target is None:
                        target = FundScore(amfi_code=row["amfi_code"])
                        db.add(target)
                    for key, value in row.items():
                        if key == "amfi_code":
                            continue
                        setattr(target, key, value)
                    target.scored_at = datetime.utcnow()
                db.commit()
            except Exception as exc:
                db.rollback()
                logger.warning("Score persist failed: {}", exc)

    # ------------------------------------------------------------------ reading
    def scored_codes(self) -> set[str]:
        self.ensure_db()
        with db_session.SessionLocal() as db:
            try:
                return {c for (c,) in db.query(FundScore.amfi_code).all()}
            except Exception:
                return set()

    def load_scores(
        self,
        *,
        exclude_fabricated: bool = True,
        min_years: Optional[float] = None,
    ) -> pd.DataFrame:
        """Persisted scores as a frame, best first.

        `min_years` filters out funds whose history is too short to rank
        fairly against the rest; ranks are computed *after* the filter so a
        excluded fund never occupies a rank position.
        """
        self.ensure_db()
        with db_session.SessionLocal() as db:
            try:
                rows = db.query(FundScore).all()
            except Exception as exc:
                logger.warning("Could not load scores: {}", exc)
                return pd.DataFrame()

        if not rows:
            return pd.DataFrame()

        records = [
            {
                "amfi_code": r.amfi_code,
                "scheme_name": r.scheme_name,
                "amc": r.amc,
                "category": r.category,
                "subcategory": r.subcategory,
                "overall": r.overall,
                "growth": r.growth,
                "risk": r.risk,
                "quality": r.quality,
                "cost_efficiency": r.cost_efficiency,
                "consistency": r.consistency,
                "diversification": r.diversification,
                "cagr": r.cagr,
                "volatility": r.volatility,
                "sharpe": r.sharpe,
                "sortino": r.sortino,
                "max_drawdown": r.max_drawdown,
                "alpha": r.alpha,
                "beta": r.beta,
                "expense_ratio": r.expense_ratio,
                "aum_cr": r.aum_cr,
                "nav_source": r.nav_source,
                "nav_points": r.nav_points,
                "years_covered": r.years_covered,
                "scored_at": r.scored_at,
            }
            for r in rows
        ]
        df = pd.DataFrame(records)
        if exclude_fabricated and not df.empty:
            df = df[df["nav_source"].apply(lambda s: classify(s) != FABRICATED)]
        if min_years is not None and not df.empty:
            df = df[df["years_covered"].fillna(0) >= float(min_years)]
        if df.empty:
            return df

        df = df.sort_values("overall", ascending=False).reset_index(drop=True)
        # Both ranks travel with every row so the overall board can always show
        # how a fund places against genuinely comparable peers.
        df["overall_rank"] = df["overall"].rank(ascending=False, method="min").astype(int)
        df["category_rank"] = (
            df.groupby("subcategory")["overall"]
            .rank(ascending=False, method="min")
            .astype(int)
        )
        df["category_size"] = df.groupby("subcategory")["overall"].transform("size")

        # Peer-relative standing: how far a fund beats its *own* category.
        #
        # Raw score is not comparable across categories. Volatility is the risk
        # input, and it does not see credit risk — so low-volatility debt
        # categories (credit risk funds above all) float to the top of a raw
        # board while carrying the default risk that wrecked several such funds
        # in 2020. Percentile-within-category sidesteps that: a fund is judged
        # only against others facing the same risks.
        df["category_percentile"] = (
            df.groupby("subcategory")["overall"].rank(pct=True, method="average") * 100
        )
        # A percentile drawn from two peers is arithmetic, not information, and
        # one drawn from an unclassified bucket compares unlike funds.
        df.loc[df["category_size"] < MIN_FUNDS_PER_CATEGORY, "category_percentile"] = None
        df.loc[~df["subcategory"].apply(is_peer_group), "category_percentile"] = None
        return df

    def top_by_category(
        self,
        n: int = 10,
        *,
        min_funds: int = MIN_FUNDS_PER_CATEGORY,
        scores: Optional[pd.DataFrame] = None,
    ) -> dict[str, pd.DataFrame]:
        """Top `n` funds within each subcategory, largest categories first."""
        df = scores if scores is not None else self.load_scores()
        if df.empty:
            return {}

        out: dict[str, pd.DataFrame] = {}
        counts = df["subcategory"].value_counts()
        for name in counts.index:
            if counts[name] < min_funds or not is_peer_group(name):
                continue
            group = df[df["subcategory"] == name].head(n)
            out[str(name)] = group.reset_index(drop=True)
        return out

    def overall_ranking(
        self,
        n: int = 50,
        *,
        scores: Optional[pd.DataFrame] = None,
        peer_relative: bool = True,
    ) -> pd.DataFrame:
        """Best funds across the whole scored universe.

        `peer_relative` ranks by percentile within category, which is the only
        cross-category comparison that means anything — see the note on
        `category_percentile`. Set it False for a raw-score board.
        """
        df = scores if scores is not None else self.load_scores()
        if df.empty:
            return df

        if peer_relative and "category_percentile" in df.columns:
            ranked = df[df["category_percentile"].notna()].sort_values(
                ["category_percentile", "overall"], ascending=False
            )
        else:
            ranked = df.sort_values("overall", ascending=False)

        return ranked.head(n).reset_index(drop=True)

    def coverage(self, min_years: Optional[float] = None) -> dict[str, Any]:
        """How much of the universe has been scored, for the UI to disclose."""
        universe = self.universe()
        scored = self.load_scores(exclude_fabricated=False)
        real = self.load_scores(exclude_fabricated=True)
        rankable = self.load_scores(exclude_fabricated=True, min_years=min_years)
        last = None
        if not scored.empty and scored["scored_at"].notna().any():
            last = pd.to_datetime(scored["scored_at"]).max()
        return {
            "universe": int(len(universe)),
            "scored": int(len(scored)),
            "rankable": int(len(rankable)),
            "excluded_fabricated": int(len(scored) - len(real)),
            "excluded_short_history": int(len(real) - len(rankable)),
            "categories": int(rankable["subcategory"].nunique()) if not rankable.empty else 0,
            "last_scored_at": last,
        }
