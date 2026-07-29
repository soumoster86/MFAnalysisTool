# Alerts (Slice B)

Real portfolio / NAV alert rules — not demo seed data.

## What fires

| Type | Scope | Default threshold | Meaning |
|------|-------|-------------------|---------|
| `nav_drop` | fund | −3% | Latest session NAV return |
| `period_return` | fund | −5% / 5d, −10% / 20d | Multi-session return |
| `drawdown` | fund | −15% | Peak-to-trough / current from peak |
| `pnl` | fund | −10% | Unrealized vs invested |
| `concentration` | portfolio | 40% | Single fund weight |
| `overlap` | portfolio | 40% | Pairwise stock holdings overlap |

### Change detection

These compare two `fund_snapshots` rows rather than reading a NAV series.

| Type | Default threshold | Meaning |
|------|-------------------|---------|
| `manager_change` | — | Fund manager on record changed |
| `expense_ratio_change` | 0.10pp | TER moved by at least this many percentage points |
| `category_change` | — | Category or sub-category reclassified |
| `benchmark_change` | — | Stated benchmark index changed |
| `holdings_change` | 20% | Portfolio turned over by weight |
| `large_holding_change` | 2pp | A single security's weight moved |
| `sector_shift` | 5pp | A sector's weight moved |
| `risk_increase` | +25% | Annualised volatility rose, or riskometer stepped up |

Thresholds are magnitudes; a rule with a non-positive threshold keeps the
default rather than firing on provider rounding noise. The dash types fire on
any difference and ignore the threshold field.

Three rules govern correctness:

1. **The first run is a baseline.** With nothing to compare against, no alert
   fires — the run reports `baselines` instead. Change alerts begin on the
   second run.
2. **Fabricated inputs are never compared.** Sample holdings are synthesised
   per fund, so diffing them would produce confident nonsense; the whole
   holdings family (`holdings_change`, `large_holding_change`, `sector_shift`)
   is skipped when either snapshot used them, and `risk_increase` is skipped on
   synthetic NAV. See `services/data/provenance.py`.
3. **A missing value is not a change.** `None → "Some Manager"` is a metadata
   backfill, not a real-world event, so both sides must be known to fire.

## Streamlit

**Alerts** page:

1. Load a portfolio (Dashboard / CAS / My Portfolios)
2. **Evaluate session portfolio** — checks live/cached NAV against rules
3. **Evaluate vault portfolios** — all saved books for the signed-in user
4. **Detect fund changes** — snapshots attributes and alerts on what moved
   since the last snapshot (first run records a baseline only)
5. Manage rules (sign-in required to persist personal rules)
6. Feed: filter, mark read, dismiss

## API

```http
GET  /api/v1/alerts
GET  /api/v1/alerts/summary
POST /api/v1/alerts/evaluate
POST /api/v1/alerts/{id}/read
POST /api/v1/alerts/read-all
GET  /api/v1/alerts/rules
POST /api/v1/alerts/rules
POST /api/v1/alerts/rules/seed
POST /api/v1/alerts/rules/{id}/toggle
DELETE /api/v1/alerts/rules/{id}
```

### Evaluate body

```json
{
  "holdings": [{ "amfi_code": "122639", "scheme_name": "...", "invested_amount": 100000, "market_value": 95000 }],
  "include_overlap": false,
  "max_funds": 20,
  "persist": true
}
```

Or vault:

```json
{ "use_vault": true, "portfolio_id": null, "max_funds": 15 }
```

## Celery beat

With `CELERY_ENABLED=true` and Redis:

```bash
celery -A workers.celery_app.celery_app worker -l info
celery -A workers.celery_app.celery_app beat -l info
```

Schedule (see `workers/celery_app.py`):

- Hourly: `evaluate_all_vault_alerts` (default portfolios / users)
- Daily: `refresh_amfi`
- Daily: `detect_all_vault_changes` — fund attributes move on the order of
  weeks and each run costs a meta + holdings fetch per fund, so a faster
  cadence buys nothing

Without Celery, evaluation runs **inline** from the UI / API (`task_always_eager` or direct calls).

## Deduping

NAV alerts get a dated `fingerprint` (`type:scope:extra:YYYY-MM-DD`), so
re-evaluation within ~20 hours does not duplicate.

Change alerts fingerprint on the **change itself** rather than the date — a
manager change should alert once, not again every scan. A *further* change to
the same field produces a different fingerprint and alerts again.

## Data model

- `alerts` — fired instances (+ user_id, portfolio_id, metric_value, fingerprint)
- `alert_rules` — user or system rules (threshold, lookback, severity, scope)
- `fund_snapshots` — point-in-time fund attributes; the only history behind
  change detection, since `funds` is overwritten in place on every refresh

Missing columns are added on both SQLite and Postgres by
`database/schema_repair.py`, which derives them from the ORM.

New rule types reach installs seeded before they existed: `get_rule_specs`
returns stored rules **plus** defaults for any type with no stored row. A type
the user disabled has a row, so it stays disabled.
