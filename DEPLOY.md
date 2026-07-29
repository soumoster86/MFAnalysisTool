# Deploy MF Analysis Tool → GitHub + Streamlit Cloud

## Architecture on Cloud

```
GitHub repo  →  Streamlit Community Cloud  →  public HTTPS app
                     │
                     ├─ secrets (API keys, SECRET_KEY, DATABASE_URL)
                     └─ ephemeral disk (/tmp) unless Postgres is configured
```

**Main file for Streamlit Cloud:** `frontend/app.py`

---

## 1. Prepare the repo (one-time)

From the project folder:

```powershell
cd "C:\Users\soumo\Python Project\MFAnalysisTool"

# Ensure secrets stay local
# .env and .streamlit/secrets.toml are already in .gitignore

git init
git add .
git status
git commit -m "Prepare MF Analysis Tool for Streamlit Cloud"
```

Create an empty GitHub repository (e.g. `MFAnalysisTool`), then:

```powershell
git branch -M main
git remote add origin https://github.com/<YOUR_USER>/MFAnalysisTool.git
git push -u origin main
```

---

## 2. Streamlit Community Cloud

1. Open [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
2. **New app**
   - Repository: `YOUR_USER/MFAnalysisTool`
   - Branch: `main`
   - **Main file path:** `frontend/app.py`
   - Python version: **3.12** (if selectable; also set via `runtime.txt`)
3. **Advanced settings → Secrets** — paste TOML (see below).
4. Deploy.

### Secrets (paste into Streamlit Cloud)

```toml
SECRET_KEY = "use-a-long-random-string-here"
APP_ENV = "production"
DEBUG = "false"

OPENAI_API_KEY = "your-key"
OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_MODEL = "gpt-5.6-sol"

# Demo / free tier (data resets when the app sleeps/reboots):
DATABASE_URL = "sqlite:////tmp/mf_analysis.db"
DATA_CACHE_DIR = "/tmp/mf_cache"
```

For **persistent** user portfolios (recommended):

```toml
DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require"
```

Free Postgres: [Neon](https://neon.tech), [Supabase](https://supabase.com), [Railway](https://railway.app).

Generate a secret key:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## 3. What works out of the box on Cloud

| Feature | Notes |
|---------|--------|
| Landing + auth | Yes (uses SQLite or Postgres) |
| Dashboard / analytics | Yes |
| AMFI + mfapi NAV | Yes (needs outbound HTTPS) |
| Groww holdings | Best-effort (unofficial API) |
| CAS PDF upload | Yes (`pdfplumber`) |
| AI Assistant | Yes if `OPENAI_*` secrets set |
| Portfolio vault | **Persists only if Postgres (or similar)** — SQLite on `/tmp` is wiped on reboot |
| Celery / Redis | Not required for Streamlit-only deploy |

---

## 4. Common deploy issues

### Install fails / times out
Heavy packages (`catboost`, `xgboost`, `lightgbm`) can slow the first build.  
Wait for the first build (can take 10–20+ minutes). If it fails, check the Streamlit build log.

`packages.txt` installs `libgomp1` for LightGBM on Linux.

### `ModuleNotFoundError: config` / imports
Main file must be `frontend/app.py` (it adds the repo root to `sys.path`).

### App reboots wipe users/portfolios
Expected with SQLite on `/tmp`. Switch `DATABASE_URL` to Postgres.

### Groww / AMFI blocked
Some hosts block scrapers; the app falls back to sample holdings / synthetic NAV when configured.

### LLM temperature error on gpt-5.x
Do not set `OPENAI_TEMPERATURE` for `gpt-5.6-sol` — the app omits it automatically.

---

## 5. Local test of production-like secrets

```powershell
# Optional: simulate secrets file (gitignored)
copy .streamlit\secrets.toml.example .streamlit\secrets.toml
# edit secrets.toml with real keys

$env:PYTHONPATH = (Get-Location).Path
streamlit run frontend/app.py
```

---

## 6. After deploy checklist

- [ ] Open public URL → landing page (login required)
- [ ] Create account → Dashboard loads
- [ ] Upload a small CAS PDF
- [ ] Save portfolio to vault
- [ ] Restart app → sign in again (with Postgres, data remains)
- [ ] AI Assistant answers when API key is set

---

## Files added for Cloud

| File | Role |
|------|------|
| `frontend/app.py` | Streamlit entry (auth gate + nav) |
| `config/cloud_bootstrap.py` | `st.secrets` → environment |
| `.streamlit/config.toml` | Dark theme + server defaults |
| `.streamlit/secrets.toml.example` | Secrets template |
| `packages.txt` | Linux system deps for Cloud |
| `runtime.txt` | Python 3.12 pin |
| `DEPLOY.md` | This guide |
