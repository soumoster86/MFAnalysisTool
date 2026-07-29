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

## Streamlit

**Alerts** page:

1. Load a portfolio (Dashboard / CAS / My Portfolios)
2. **Evaluate session portfolio** — checks live/cached NAV against rules
3. **Evaluate vault portfolios** — all saved books for the signed-in user
4. Manage rules (sign-in required to persist personal rules)
5. Feed: filter, mark read, dismiss

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

Without Celery, evaluation runs **inline** from the UI / API (`task_always_eager` or direct calls).

## Deduping

Each fired alert gets a `fingerprint` (`type:scope:extra:YYYY-MM-DD`). Re-evaluation within ~20 hours does not create a duplicate.

## Data model

- `alerts` — fired instances (+ user_id, portfolio_id, metric_value, fingerprint)
- `alert_rules` — user or system rules (threshold, lookback, severity, scope)

SQLite older DBs get new `alerts` columns via best-effort `ALTER TABLE`.
