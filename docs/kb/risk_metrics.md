# Risk and return metrics

## Alpha

Alpha is the return a fund earned beyond what its market exposure alone would
explain. It comes from the CAPM regression of fund returns against the
benchmark:

    alpha = mean(fund_return) - [ rf_daily + beta * (mean(benchmark_return) - rf_daily) ]

annualised by multiplying by the trading days in a year.

A positive alpha means the manager added value after accounting for the risk
they took. A negative alpha means you would have done better holding the index
at the same beta. Alpha is only meaningful against the *right* benchmark — a
small-cap fund measured against NIFTY 50 will show alpha that is really just
small-cap exposure.

In this app alpha is computed in `RiskMetricsCalculator.beta_alpha`.

## Beta

Beta measures how much a fund moves when the market moves. It is the slope of
fund returns regressed on benchmark returns:

    beta = covariance(fund, benchmark) / variance(benchmark)

- Beta near 1.0 — moves roughly with the market.
- Beta above 1.0 — amplifies market moves in both directions. A beta of 1.3
  implies roughly a 13% move for every 10% market move.
- Beta below 1.0 — defensive; dampens market moves.

Beta says nothing about whether a fund is good. It describes sensitivity, not
quality. A high-beta fund is not riskier in absolute terms if its underlying
holdings are sound; it is simply more tied to the market cycle.

## Standard deviation (volatility)

The annualised standard deviation of daily returns:

    volatility = std(daily_returns) * sqrt(trading_days_per_year)

It captures dispersion in both directions, so it penalises large gains as much
as large losses. That is its main weakness, and why Sortino exists.

## Sharpe ratio

Return earned per unit of total risk:

    sharpe = (annualised_return - risk_free_rate) / annualised_volatility

Higher is better. Sharpe is useful for comparing funds *within the same
category*. Comparing a liquid fund's Sharpe against an equity fund's is
meaningless — they are exposed to different risks entirely.

A Sharpe computed on fewer than a couple of years of data is unstable and
should not drive a decision on its own.

## Sortino ratio

Sharpe's flaw is that it treats upside volatility as risk. Sortino fixes that
by dividing only by *downside* deviation:

    sortino = (annualised_return - risk_free_rate) / downside_deviation

where downside deviation uses only returns below the target. A fund with
violent upswings and shallow drawdowns will score poorly on Sharpe but well on
Sortino — and Sortino is the more honest measure for an investor who only
minds losses.

## Treynor ratio

Excess return per unit of *market* risk rather than total risk:

    treynor = (annualised_return - risk_free_rate) / beta

Use Treynor when the fund is one holding inside a diversified portfolio, where
its stock-specific risk is already diluted and only market exposure matters.
Use Sharpe when the fund is the whole portfolio.

## Information ratio

Consistency of outperformance against the benchmark:

    information_ratio = mean(active_return) / std(active_return) * sqrt(trading_days)

where active return is fund return minus benchmark return. Its denominator,
the standard deviation of active return, is called tracking error. A high
information ratio means the manager beats the benchmark *reliably*, not just
by a large amount once.

## Maximum drawdown

The worst peak-to-trough fall the fund has suffered:

    drawdown_series = (nav - running_maximum(nav)) / running_maximum(nav)
    max_drawdown = min(drawdown_series)

Reported as a negative number, so −0.35 means the fund lost 35% from its high
point. This is usually the number that matters most to a real investor,
because it describes the loss they would have had to sit through without
selling.

Recovering from a drawdown takes more than the fall: a 50% loss needs a 100%
gain to get back to even.

## Upside and downside capture

How much of the benchmark's movement the fund captured, measured separately in
rising and falling markets:

- Upside capture 110% — the fund gained 10% more than the index in up periods.
- Downside capture 80% — the fund lost only 80% of what the index lost when it
  fell.

The capture ratio is upside divided by downside. Above 1.0 is favourable. A
fund with 90% upside and 70% downside capture is a strong defensive choice
even though it lags in a bull run.

## Calmar ratio

Annualised return divided by the absolute maximum drawdown. It answers "how
much return did I get for the worst loss I had to endure?"

## VaR and CVaR

Value at Risk at 5% is the daily loss that is exceeded only 5% of the time.
Conditional VaR (also called expected shortfall) is the average loss on those
worst 5% of days, and is the more useful of the two because it describes how
bad the tail actually gets rather than just where it starts.
