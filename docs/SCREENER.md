# Screener

Ranks the fund universe by health score — top 10 in each category, plus an
overall board.

## How it runs

Scoring a fund means fetching its NAV history, and the universe is ~2,500
Direct Growth schemes, so scoring cannot happen during a page render. Scores
are computed in bounded batches (8 parallel fetches), persisted to
`fund_scores`, and the page reads from that table. A nightly beat task
(`score_fund_universe`) re-scores 500 at a time.

Universe = **Direct Growth plans only**. Regular plans hold the same portfolio
at a higher TER and IDCW plans have a NAV that drops on payout, so including
either would fill the ranking with duplicates of the same fund.

## Scores are NAV-based

The screener uses the same `FundHealthScorer` as the Fund Health page but skips
the stock-level holdings fetch, which is the slow call. The two holdings
factors — top-10 concentration and holdings count — are absent and scored
neutral, so **a screener score can differ slightly from the Fund Health page's
score for the same fund**. `has_holdings` records which kind a row is.

## What is excluded, and why

| Exclusion | Reason |
|-----------|--------|
| Synthetic NAV | Ranking fabricated performance beside real performance is worse than omitting the fund. See `services/data/provenance.py`. |
| Under ~1 year of NAV | Risk metrics are too unstable to store. |
| Under 3 years (default, adjustable) | A few months of data can post a flattering annualised return off one good run. |
| NAV move > 25% in a day | A unit rebasing or segregated-portfolio restoration, not a return. Real cases in the AMFI feed: **+900%** in one day on an overnight fund, **+169%** on a wound-down debt fund. One such jump makes CAGR and volatility meaningless. |
| `unclaimed`, `I.E.F.`, `segregated`, `side pocket` plans | Administrative vehicles, not investable products. |
| Categories with fewer than 3 scored funds | A league table of two is noise. |
| `Unclassified` | AMFI leaves ~a third of schemes uncategorised; the bucket holds medium-duration debt beside innovation equity, so it is not a peer group. |

Near-zero volatility is handled in `RiskMetricsCalculator`: below 0.5%
annualised, Sharpe and Sortino are reported as **absent** rather than as a
number. An overnight fund at 0.12% volatility otherwise turns a few basis
points of shortfall into a Sharpe of −16, which reads as catastrophic and means
nothing.

## The two boards

**Top 10 by category** — funds ranked against their own peers. This is the
straightforward, defensible ranking.

**Overall** — offers two modes:

- **Peer-relative (default)** — ranks by percentile within category. This is
  the only cross-category comparison that holds.
- **Raw score** — ranks on score alone, with a warning.

The reason the default is peer-relative is concrete, not theoretical. The
score's risk input is volatility, and volatility does not see credit risk. On
the current data a raw board puts **six credit risk funds in the top ten**:
steady NAV, high Sharpe, and the default risk that wrecked several such funds
in 2020 nowhere in the number. Percentile-within-category avoids that by only
ever comparing funds that face the same risks.

## Caveats

Scores rank risk-adjusted history. They are not investment advice, and past
performance does not predict future returns.
