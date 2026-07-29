# API Design (FastAPI)

Base URL: `http://localhost:8000`

Interactive docs: `/docs` · ReDoc: `/redoc`

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness |
| POST | `/api/v1/auth/register` | Create account (+ token) |
| POST | `/api/v1/auth/login` | Login → JWT |
| GET | `/api/v1/auth/me` | Current user (Bearer) |
| GET/POST | `/api/v1/portfolios` | List / create vault portfolios |
| GET | `/api/v1/portfolios/default` | Default portfolio |
| GET/PUT/DELETE | `/api/v1/portfolios/{id}` | Portfolio detail / update / delete |
| GET | `/api/v1/funds/search?q=&category=&limit=` | Search AMFI schemes |
| GET | `/api/v1/funds/{amfi_code}` | Analytics + health + holdings |
| GET | `/api/v1/funds/{amfi_code}/nav?years=5` | Real historical NAV (mfapi/TigZig) |
| GET | `/api/v1/funds/{amfi_code}/holdings` | Live holdings (Groww) |
| GET | `/api/v1/funds/{amfi_code}/xray` | Fund X-Ray report |
| POST | `/api/v1/portfolio/analyze` | Portfolio analysis body `{holdings: [...]}` |
| POST | `/api/v1/portfolio/import-cas` | Upload MFCentral CAS Summary PDF → mapped holdings |
| POST | `/api/v1/goals/plan` | Monte Carlo goal plan |
| POST | `/api/v1/recommend` | Recommendation engine |
| POST | `/api/v1/optimize` | Portfolio optimizer |
| POST | `/api/v1/chat` | AI assistant |
| GET | `/api/v1/alerts` | List alerts (+ unread summary) |
| GET | `/api/v1/alerts/summary` | Unread counts by severity |
| POST | `/api/v1/alerts/evaluate` | Run real rules on holdings / vault |
| POST | `/api/v1/alerts/{id}/read` | Mark one alert read |
| POST | `/api/v1/alerts/read-all` | Mark all read |
| GET | `/api/v1/alerts/rules` | List rules (defaults or user) |
| POST | `/api/v1/alerts/rules` | Create/update rule (auth) |
| POST | `/api/v1/alerts/rules/seed` | Seed default rules (auth) |
| POST | `/api/v1/admin/sync-amfi` | Sync AMFI → SQLite |

## Example

```bash
curl -X POST http://localhost:8000/api/v1/goals/plan \
  -H "Content-Type: application/json" \
  -d '{"age":30,"retirement_age":60,"current_investment":500000,"monthly_sip":20000,"expected_return":0.12}'
```
