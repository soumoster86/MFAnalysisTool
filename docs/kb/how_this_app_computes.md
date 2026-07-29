# How this app computes what it shows

## Fund health score

`FundHealthScorer` produces a 0–100 score from up to fourteen factors, grouped
into six sub-scores: growth, risk, quality, cost efficiency, consistency and
diversification.

Factors include CAGR, alpha, relative CAGR against category, maximum drawdown,
volatility, beta, Sharpe, Sortino, rolling consistency, information ratio,
expense ratio, manager tenure, AUM, top-10 concentration and holdings count.

Missing data is handled by scoring that factor neutral (50) and down-weighting
it in the blend, rather than dropping it or guessing. A fund with sparse data
therefore trends toward the middle of the range instead of scoring falsely high
or low.

A health score is a relative comparison aid, not a recommendation.

## Where the numbers come from

NAV history is fetched from mfapi.in, with a TigZig AMFI mirror as fallback and
a local database cache. Holdings come from Groww's public scheme API. AMFI's
daily NAV file supplies the scheme master.

When every live provider fails, the app can substitute a **synthetic** NAV path
or **sample** holdings so the interface still renders. Any figure computed from
those inputs is fabricated and is labelled as such on screen — see
`services/data/provenance.py`. Never present a metric derived from synthetic
data as real performance.

## Alerts

Two families:

- **NAV and portfolio rules** evaluated against a time series: NAV drop, period
  return, drawdown, unrealised P&L, fund concentration, holdings overlap.
- **Change detection**, which compares two point-in-time snapshots of a fund:
  manager change, expense ratio change, category change, benchmark change,
  portfolio turnover, large holding change, sector shift, risk increase.

Change alerts need history, so the first capture of a fund records a baseline
and fires nothing. Changes derived from fabricated data are suppressed.

## Goal planning

The goal planner runs a Monte Carlo simulation over the assumed return and
volatility, reporting the probability of reaching the target along with worst,
average and best case corpus outcomes, plus the SIP or return required to close
a shortfall.

Monte Carlo assumes returns are drawn from a stable distribution. Real markets
have fatter tails and regime changes, so treat the probability as a planning
aid rather than a forecast.

## Machine learning

`ModelTrainer` compares Random Forest, Gradient Boosting, XGBoost, LightGBM,
CatBoost and a stacking ensemble, selecting the best by cross-validated RMSE.

Validation uses `TimeSeriesSplit` so no future data leaks into training, and
the feature set excludes forward returns. Features are engineered from NAV:
rolling returns, momentum, volatility, moving averages, rolling Sharpe and
Sortino, rolling alpha and beta, RSI, MACD, drawdown, plus expense ratio, AUM
and manager tenure.

Predicted returns are model output on historical patterns. They are not
forecasts and must never be presented as expected performance.

## What this app will not tell you

It does not give personalised investment advice, and nothing in it constitutes
a recommendation to buy or sell. It analyses the portfolio you give it and
explains what the numbers mean. Decisions, and the responsibility for them,
stay with you — and a licensed adviser is the right place for personal advice.
