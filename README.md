# MF Analysis Tool

**AI & Machine Learning powered Mutual Fund Analysis Platform** (Phase 1 skeleton).

Not another plain screener — an investment assistant for understanding, comparing, analyzing, and optimizing mutual fund portfolios.

> **Disclaimer:** Educational software only. Not SEBI-registered advice. Validate all data before investment decisions.

---

## Features (15 modules)

| # | Module | Status |
|---|--------|--------|
| 1 | Dashboard | ✅ Portfolio score, P&L, allocations, charts |
| 2 | Mutual Fund Database | ✅ Live AMFI feed + SQLite |
| 3 | Fund Health Score | ✅ 0–100 multi-pillar model |
| 4 | Portfolio Analyzer | ✅ Risk, correlation, concentration |
| — | **MFCentral CAS Upload** | ✅ Import SoA + Demat holdings from CAS PDF |
| — | **Portfolio Vault (Slice A)** | ✅ Register/login · save/load portfolios · CAS re-open |
| 5 | Overlap Detector | ✅ Holdings / AMC / category overlap |
| 6 | Fund Comparison | ✅ Up to 5 funds + AI summary |
| 7 | Goal Planner | ✅ Monte Carlo, required SIP/return |
| 8 | ML Engine | ✅ RF/GBM/XGB/LGBM/CatBoost/Stacking |
| 9 | Recommendations | ✅ Risk-profile → allocation |
| 10 | Portfolio Optimizer | ✅ MPT, risk parity, simple BL |
| 11 | Fund X-Ray | ✅ Hidden risks, style, alternatives |
| 12 | AI Assistant | ✅ OpenAI-compatible + offline fallback |
| 13 | Alerts | ✅ Rules + Celery stubs |
| 14 | Visualizations | ✅ Plotly gallery |
| 15 | Reports | ✅ PDF / Excel / PowerPoint |

---

## Deploy (GitHub + Streamlit Cloud)

See **[DEPLOY.md](DEPLOY.md)** for full steps.

- **Main file:** `frontend/app.py`
- **Secrets:** Streamlit Cloud → App settings → Secrets (template: `.streamlit/secrets.toml.example`)
- **Python:** 3.12 (`runtime.txt`)
- **Persistent portfolios:** set `DATABASE_URL` to Postgres (SQLite on Cloud is ephemeral)

---

## Quick start (local)

### 1. Create environment

```powershell
cd "C:\Users\soumo\Python Project\MFAnalysisTool"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Configure

```powershell
copy .env.example .env
# Optional: set OPENAI_API_KEY for full AI chat
```

### 3. Run Streamlit UI

```powershell
python run_ui.py
# or
streamlit run frontend/app.py
```

Open **http://localhost:8501**

### 4. Run FastAPI (optional)

```powershell
python run_api.py
```

Open **http://localhost:8000/docs**

### 5. Tests

```powershell
pytest -q
```

---

## Tech stack

- **Python 3.12+** · FastAPI · Streamlit · Pandas · NumPy  
- **Scikit-Learn · XGBoost · LightGBM · CatBoost**  
- **yfinance · AMFI NAVAll** · SQLAlchemy / SQLite  
- **Celery + Redis** (optional stubs) · OpenAI-compatible LLM  
- **Plotly · ReportLab · python-pptx · openpyxl**

---

## Data sources

| Source | Use |
|--------|-----|
| [AMFI NAVAll.txt](https://www.amfiindia.com/spages/NAVAll.txt) | Scheme master + latest NAV |
| [mfapi.in](https://www.mfapi.in/) | **Real historical NAV** (primary) |
| [TigZig MF NAV API](https://www.tigzig.com/apis/mf-nav) | Historical NAV fallback |
| Groww public scheme API | **Live portfolio holdings** + TER / AUM / manager (unofficial) |
| yfinance | Benchmarks (NIFTY, SENSEX, …) |
| Synthetic NAV / sample holdings | Offline fallback only if live providers fail |

Each analytics payload includes a `data_sources` block so the UI can show whether NAV/holdings are live or fallback.

---

## Project structure

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/API.md](docs/API.md), [docs/DATABASE.md](docs/DATABASE.md).

```
backend-ready packages: api/, analytics/, ml/, services/, models/, database/, workers/
frontend/: Streamlit multipage app
tests/, docs/, config/, utils/
```

---

## Docker

```powershell
docker compose up --build app
# API: docker compose up api
# Worker: docker compose --profile workers up worker
```

---

## ASCII UI mockup

```
┌──────────────────────────────────────────────────────────┐
│  MF Analysis Tool                    [Dark · Bloomberg]  │
├────────────┬─────────────────────────────────────────────┤
│ Dashboard  │  Portfolio Value    Health 78    Daily P&L  │
│ Fund DB    │  ┌─────────────┐  ┌─────────────────────┐   │
│ Health     │  │ NAV Chart   │  │ Risk Gauge          │   │
│ Analyzer   │  └─────────────┘  └─────────────────────┘   │
│ Overlap    │  Sector Treemap · Allocation Pie · Table    │
│ Compare    │                                             │
│ Goals …    │                                             │
└────────────┴─────────────────────────────────────────────┘
```

---

## Environment variables

See `.env.example` for `DATABASE_URL`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`, Redis/Celery flags, and AMFI cache settings.

---

## License

Private / personal project — add a license before public distribution.
