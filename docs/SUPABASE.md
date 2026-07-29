# Supabase Postgres for persistent data

Use Supabase so **users and portfolio vault** survive Streamlit Cloud reboots.

## What is stored in Postgres

| Tables | Purpose |
|--------|---------|
| `users` | Accounts (email + password hash) |
| `portfolios` | Named vaults |
| `portfolio_holdings` | Funds in each vault |
| `funds` / `fund_navs` / `fund_holdings` / … | Optional app cache (also uses `/tmp` files) |

Market data caches (AMFI CSV, NAV history files) still live on disk (`DATA_CACHE_DIR`) and may rebuild after reboot — that is OK. **Accounts + saved portfolios** need Postgres.

---

## 1. Get the connection string from Supabase

1. Open [Supabase Dashboard](https://supabase.com/dashboard) → your project  
2. **Project Settings** (gear) → **Database**  
3. Under **Connection string**, choose **URI**  
4. Prefer one of:

### Option A — Direct connection (simplest for this app)

- Mode: **Session** or **Direct**  
- Host looks like: `db.<project-ref>.supabase.co`  
- Port: **5432**

Example (password will be your database password):

```text
postgresql://postgres:YOUR_PASSWORD@db.YOUR_PROJECT_REF.supabase.co:5432/postgres
```

### Option B — Pooler (if direct is blocked)

- Host contains `pooler.supabase.com`  
- Port **6543** (transaction) or **5432** (session)  
- Prefer **Session mode** when available  

```text
postgresql://postgres.YOUR_PROJECT_REF:YOUR_PASSWORD@aws-0-REGION.pooler.supabase.com:5432/postgres
```

Copy the URI, then replace `[YOUR-PASSWORD]` with the real DB password  
(Project Settings → Database → **Database password**).

---

## 2. Streamlit Cloud secrets

In Streamlit Cloud → your app → **Settings → Secrets**, set:

```toml
SECRET_KEY = "your-long-random-hex"
APP_ENV = "production"
DEBUG = "false"

OPENAI_API_KEY = "your-openai-key"
OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_MODEL = "gpt-5.6-sol"

# Paste Supabase URI — app normalizes to postgresql+psycopg:// and adds sslmode=require
DATABASE_URL = "postgresql://postgres:YOUR_PASSWORD@db.YOUR_PROJECT_REF.supabase.co:5432/postgres"

DATA_CACHE_DIR = "/tmp/mf_cache"
```

**Do not** keep `sqlite:////tmp/mf_analysis.db` if you want persistence.

Save secrets → **Reboot app**.

---

## 3. Tables are created automatically

On app start, `init_db()` runs `CREATE TABLE IF NOT EXISTS` for all models.  
You do **not** need to run SQL by hand for a new empty Supabase project.

Optional local check:

```powershell
cd "C:\Users\soumo\Python Project\MFAnalysisTool"
$env:DATABASE_URL = "postgresql://postgres:YOUR_PASSWORD@db.xxx.supabase.co:5432/postgres"
$env:PYTHONPATH = (Get-Location).Path
.\.venv\Scripts\python.exe scripts\init_db.py
```

In Supabase → **Table Editor**, you should see `users`, `portfolios`, `portfolio_holdings`, etc.

---

## 4. Verify after deploy

1. Open the app → landing page  
2. **Create account**  
3. Supabase → Table Editor → `users` has a row  
4. Upload CAS → **Save to vault**  
5. Supabase → `portfolios` / `portfolio_holdings` have rows  
6. **Reboot** Streamlit app → sign in again → portfolio still there  

---

## 5. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Database connection failed` on landing | Wrong password, or IP restrictions (Supabase free usually allows all; check DB password) |
| `password authentication failed` | Reset DB password in Supabase; update secrets |
| `SSL connection required` | App adds `sslmode=require` for `*.supabase.co` automatically — ensure URL host is correct |
| Pooler prepared statement errors | Use **direct** `db.*.supabase.co:5432` or **session** pooler; app disables prepared statements on pooler port 6543 |
| Still losing data after reboot | Confirm secrets show Postgres URL, not sqlite `/tmp` |
| Special characters in password | URL-encode them (`@` → `%40`, `#` → `%23`, etc.) |

---

## 6. Local `.env` (optional)

```env
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@db.YOUR_PROJECT_REF.supabase.co:5432/postgres
SECRET_KEY=local-dev-secret
```

Then:

```powershell
python scripts/init_db.py
python run_ui.py
```
