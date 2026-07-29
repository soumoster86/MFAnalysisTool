# MF Analysis Tool — Architecture

## Goal

Intelligent mutual fund investment assistant (not a plain screener) with analytics, ML ranking, portfolio optimization, and an LLM assistant.

## Phase 1 stack

| Layer | Choice |
|-------|--------|
| UI | Streamlit (dark Bloomberg-inspired) |
| API | FastAPI + OpenAPI (`/docs`) |
| DB | SQLite (Postgres-ready SQLAlchemy models) |
| Queue | Celery + Redis stubs (`CELERY_ENABLED=false` → eager/local) |
| Data | AMFI NAVAll.txt + yfinance benchmarks |
| ML | sklearn + XGBoost + LightGBM + CatBoost + stacking |
| LLM | OpenAI-compatible API (`OPENAI_API_KEY`) |

## Package layout

```
MFAnalysisTool/
  api/           FastAPI app
  analytics/     Pure quant logic (risk, health, overlap, optimizer, goals, xray)
  ml/            Features, training, recommendations
  services/      Data, portfolio, AI, alerts, reports
  models/        SQLAlchemy ORM
  database/      Engine / sessions
  frontend/      Streamlit multipage UI
  workers/       Celery tasks
  config/        Settings
  tests/         Pytest
  docs/          Documentation
```

## Data notes

- **AMFI** (`NAVAll.txt`) — scheme master + latest NAV.
- **Historical NAV** (real):
  1. Primary: [mfapi.in](https://www.mfapi.in/) `GET /mf/{amfi_code}`
  2. Fallback: [TigZig AMFI API](https://www.tigzig.com/apis/mf-nav) `GET /mf/v1/nav?scheme=`
  3. Disk cache under `data/cache/nav_history/`
  4. SQLite `fund_navs` persistence (optional)
  5. Synthetic GBM path only if all live sources fail (`ALLOW_SYNTHETIC_NAV_FALLBACK`)
- **Holdings** (real):
  1. Groww public scheme API (unofficial): search → `v2/scheme/search/{search_id}` → `holdings[]`
  2. Disk cache under `data/cache/holdings/`
  3. SQLite `fund_holdings` snapshot
  4. Deterministic sample books only if live lookup fails (`ALLOW_SAMPLE_HOLDINGS_FALLBACK`)
- Enrichment from Groww also supplies **expense ratio, AUM, fund manager, benchmark, exit load**.

## Module map

| # | Module | Primary code |
|---|--------|----------------|
| 1 | Dashboard | `frontend/pages/1_Dashboard.py` |
| 2 | Fund DB | `services/data/amfi_client.py` |
| 3 | Health Score | `analytics/health_score.py` |
| 4 | Portfolio Analyzer | `services/portfolio/analyzer.py` |
| 5 | Overlap | `analytics/overlap.py` |
| 6 | Comparison | `frontend/pages/6_Fund_Comparison.py` |
| 7 | Goal Planner | `analytics/goal_planner.py` |
| 8 | ML Engine | `ml/` |
| 9 | Recommendations | `ml/recommender.py` |
| 10 | Optimizer | `analytics/optimizer.py` |
| 11 | X-Ray | `analytics/xray.py` |
| 12 | AI Assistant | `services/ai/assistant.py` |
| 13 | Alerts | `services/alerts/`, `workers/tasks.py` |
| 14 | Visualizations | `frontend/components/charts.py` |
| 15 | Reports | `services/reports/report_service.py` |

## Clean architecture flow

```
UI / API  →  services  →  analytics|ml  →  data clients / DB
```

Business rules live in `analytics/` and `ml/`. IO and orchestration live in `services/`.

## Production roadmap

1. ~~Real historical NAV + holdings vendor~~ (mfapi + Groww)
2. PostgreSQL + Alembic migrations (SQLAlchemy ready; SQLite default)
3. ~~JWT auth multi-user portfolios~~ (Slice A — vault)
4. Celery beat schedules for alerts
5. React/Next.js Phase 2 frontend against FastAPI

See also: [PORTFOLIO_VAULT.md](PORTFOLIO_VAULT.md)
