# Portfolio Vault (Slice A)

Save and reopen mutual fund portfolios across sessions.

## Features

- **Register / login** (JWT + PBKDF2 password hashes)
- **Save** current working holdings (including CAS imports)
- **List / load / rename / delete** portfolios
- **Default portfolio** auto-loads on next sign-in
- Works with **SQLite** (default) or **PostgreSQL** (`DATABASE_URL`)

## Streamlit UI

| Surface | Purpose |
|---------|---------|
| **Landing page** | Auth gate — sign in / create account required before app access |
| **Account** | Profile + sign out (signed-in only) |
| **My Portfolios** | Vault CRUD + load into Dashboard/Analyzer |
| **Upload CAS** | After apply → **Save CAS portfolio to vault** |

Unauthenticated users only see the landing page. Sidebar shows email + sign out when inside the app.

## API

```http
POST /api/v1/auth/register   { "email", "password", "full_name?" }
POST /api/v1/auth/login      { "email", "password" }
GET  /api/v1/auth/me         Authorization: Bearer <token>

GET    /api/v1/portfolios
POST   /api/v1/portfolios
GET    /api/v1/portfolios/default
GET    /api/v1/portfolios/{id}
PUT    /api/v1/portfolios/{id}
DELETE /api/v1/portfolios/{id}
```

## Typical flow

1. **Account** → create account  
2. **Upload CAS** → parse → apply → **Save to vault**  
3. Close app / restart  
4. **Account** → sign in (default portfolio loads)  
   or **My Portfolios** → Load into app  

## Database

Default: `sqlite:///./data/mf_analysis.db`

PostgreSQL example:

```env
DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/mf_analysis
```

New columns are added best-effort on SQLite via `ALTER TABLE` in `PortfolioVaultService._ensure_schema`.

## Security notes

- Passwords: PBKDF2-SHA256 (stdlib)
- JWT: HS256 using `SECRET_KEY` from settings
- Educational product — use HTTPS and a strong secret in production
