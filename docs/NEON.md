# Neon Postgres — persistent data for Streamlit Cloud

Use [Neon](https://neon.tech) so **users** and **portfolio vault** survive app reboots.

## What gets stored

| Table | Purpose |
|-------|---------|
| `users` | Login accounts |
| `portfolios` | Named saved portfolios |
| `portfolio_holdings` | Funds inside each portfolio |
| Other `fund_*` tables | Optional cache (may also use `/tmp` files) |

---

## 1. Create a Neon project

1. Sign up / log in at [console.neon.tech](https://console.neon.tech)
2. **New Project** → pick a name (e.g. `mf-analysis`) and region
3. Create project

---

## 2. Copy the connection string

1. In the project dashboard, open **Connection details** (or **Dashboard → Connect**)
2. Select:
   - **Driver:** any / “Postgres”
   - **Connection:** prefer **Pooled connection** for Streamlit Cloud **or** Direct — both work  
     - Pooled host often looks like: `ep-xxxx-pooler.region.aws.neon.tech`  
     - Direct: `ep-xxxx.region.aws.neon.tech`
3. Copy the URI. It looks like:

```text
postgresql://neondb_owner:npg_xxxxx@ep-cool-name-a1b2c3d4-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
```

Or without query string:

```text
postgresql://neondb_owner:npg_xxxxx@ep-cool-name-a1b2c3d4.ap-southeast-1.aws.neon.tech/neondb
```

The app will:

- Switch to `postgresql+psycopg://…`
- Add `sslmode=require` if missing
- Disable prepared statements on pooler hosts (`-pooler` / port 6543)

---

## 3. Streamlit Cloud secrets

App → **Settings → Secrets** — replace your old SQLite line with Neon:

```toml
SECRET_KEY = "your-existing-long-random-hex"
APP_ENV = "production"
DEBUG = "false"

OPENAI_API_KEY = "your-key"
OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_MODEL = "gpt-5.6-sol"

# Paste the Neon connection string (password included)
DATABASE_URL = "postgresql://neondb_owner:npg_xxxxx@ep-xxxx-pooler.region.aws.neon.tech/neondb?sslmode=require"

DATA_CACHE_DIR = "/tmp/mf_cache"
```

**Remove** any:

```toml
DATABASE_URL = "sqlite:////tmp/mf_analysis.db"
```

Save → **Reboot** the app.

---

## 4. Tables are created automatically

On startup the app runs `init_db()` → creates tables if missing.  
No manual SQL required.

Optional local test:

```powershell
cd "C:\Users\soumo\Python Project\MFAnalysisTool"
$env:DATABASE_URL = "postgresql://neondb_owner:npg_xxx@ep-xxx.region.aws.neon.tech/neondb?sslmode=require"
$env:PYTHONPATH = (Get-Location).Path
.\.venv\Scripts\python.exe scripts\init_db.py
```

In Neon → **Tables** you should see `users`, `portfolios`, `portfolio_holdings`, etc.

---

## 5. Verify persistence

1. Open the live Streamlit app  
2. Create an account on the landing page  
3. Neon → **Tables** → `users` has a row  
4. Import CAS → **Save to vault**  
5. Neon → `portfolios` / `portfolio_holdings` populated  
6. Streamlit → **Reboot app** → sign in again → portfolio still loads  

---

## 6. Troubleshooting

| Problem | Fix |
|---------|-----|
| `Database connection failed` | Password wrong, or URI truncated in secrets (quotes/newlines) |
| Password has special characters | URL-encode (`@`→`%40`, `#`→`%23`, `/`→`%2F`) |
| `SSL required` | App adds `sslmode=require` for `*.neon.tech`; keep it in the URI if you like |
| Connection timeout | Try **pooled** endpoint (`-pooler` in hostname) |
| Still losing data after reboot | Confirm Secrets show Neon URL, not `sqlite:////tmp/...` |
| Branch compute sleeping | Neon free tier may cold-start (first request a few seconds slower) |

---

## 7. Local `.env` (optional)

```env
DATABASE_URL=postgresql://neondb_owner:npg_xxx@ep-xxx.region.aws.neon.tech/neondb?sslmode=require
SECRET_KEY=local-dev-secret
```

```powershell
python scripts/init_db.py
python run_ui.py
```
