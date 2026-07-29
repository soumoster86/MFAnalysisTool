# Database Design

SQLAlchemy 2.0 models · SQLite file `data/mf_analysis.db` (Phase 1).

## Tables

### `funds`
Master scheme: `amfi_code` (unique), name, AMC, category, subcategory, expense, AUM, allocations, latest NAV, health_score.

### `fund_navs`
`(fund_id, nav_date)` unique · historical NAV points.

### `fund_holdings`
Security, sector, market_cap, weight_pct, country, asset_type.

### `fund_metrics`
Cached risk metrics by period (`1Y`/`3Y`/`5Y`).

### `portfolios` / `portfolio_holdings`
Named portfolios and line items (units, invested, SIP).

### `alerts`
Fired alerts: type, severity, title/message, optional `user_id` / `portfolio_id` / `rule_id`, `metric_value`, `threshold`, `fingerprint` (dedupe), read flag.

### `alert_rules`
User or system rules: `alert_type`, `threshold`, `lookback_days`, `severity`, `scope` (fund|portfolio), `enabled`.

### `users`
JWT auth (email, hashed_password, flags).

## Migrations

Phase 1 uses `Base.metadata.create_all`. For production, introduce Alembic against PostgreSQL (`DATABASE_URL=postgresql+psycopg://...`).
