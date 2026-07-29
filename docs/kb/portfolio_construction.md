# Portfolio construction

## Fund overlap

Two funds overlap when they hold the same securities. Overlap is measured as
the sum of the minimum weight of each shared holding across the two funds:

    overlap = sum over shared securities of min(weight_in_A, weight_in_B)

Overlap above roughly 40% between two funds means you are largely paying two
expense ratios for one portfolio. This is the most common flaw in retail
portfolios in India: four large-cap funds from four AMCs are close to a single
expensive index fund, because they all draw from the same 100 stocks.

Diversification comes from holding *different* things — market caps,
geographies, asset classes — not from holding more funds.

## Concentration

Two distinct concentrations matter:

- **Fund concentration** — one fund is too large a share of your portfolio.
  Above about 40% of the book, that fund's fate is your portfolio's fate.
- **Stock concentration** — a single security carries a large weight after
  looking through all your funds. You can hold six funds and still have 9% in
  one bank because every one of them owns it.

The second is invisible unless you look through to holdings, which is what the
overlap and X-Ray modules do.

## Asset allocation

The split across equity, debt, gold and cash explains most of the variance in
portfolio outcomes — far more than which particular fund you picked within a
category. Getting allocation right and the fund choice roughly right beats the
reverse.

Rebalancing back to a target allocation enforces selling what has run and
buying what has lagged, which is mechanically counter-cyclical.

## Market cap allocation

- **Large cap** — the top 100 companies. Lower volatility, lower long-run
  return, higher liquidity.
- **Mid cap** — companies 101 to 250. Higher growth, materially deeper
  drawdowns.
- **Small cap** — 251 onward. Highest potential return, brutal drawdowns
  (falls of 50–60% have occurred), and real liquidity risk in a crisis.

Small and mid caps require a genuinely long horizon — a 7 to 10 year view — and
the temperament to not sell at the bottom.

## Correlation

Correlation runs from −1 to +1 and describes whether two holdings move
together. Near 1.0 means they are effectively the same exposure. Diversification
requires assets with low or negative correlation to each other.

The trap: correlations rise toward 1 during crises, exactly when
diversification is needed most. Equity diversification alone does not protect
you in a crash; different *asset classes* do.

## Modern Portfolio Theory and the efficient frontier

MPT constructs portfolios that maximise expected return for a given level of
risk. Plotting those optimal portfolios gives the efficient frontier. Anything
below the frontier is inefficient — you could get more return for the same
risk.

Key implementations in this app:

- **Maximum Sharpe** — the highest risk-adjusted return portfolio.
- **Minimum variance** — the lowest-volatility portfolio, ignoring return.
- **Risk parity** — weights so each holding contributes equally to total risk,
  rather than equal money in each.
- **Black-Litterman** — blends market-implied equilibrium returns with the
  investor's own views, which produces more stable weights than raw mean
  variance.

The honest caveat: all of these optimise on *historical* covariance and
returns. Expected returns estimated from the past are notoriously unreliable,
so mean-variance output is highly sensitive to its inputs. Treat the weights as
an input to judgement, not an instruction.

## SIP and rupee cost averaging

A systematic investment plan buys a fixed amount at a fixed interval, so you
buy more units when prices are low and fewer when high. It removes timing
decisions and enforces discipline through drawdowns.

SIP does not guarantee a profit and does not protect against a falling market.
Its real value is behavioural: it keeps you invested when you would otherwise
stop.

Stopping a SIP during a market fall is usually the single most costly mistake
an investor makes, because it forgoes exactly the cheap units that drive the
eventual recovery.
