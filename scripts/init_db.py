"""Create application tables on the configured database (SQLite or Supabase Postgres)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    from config.db_url import normalize_database_url
    from config.settings import settings
    from database.session import init_db, rebind_engine_from_settings

    url = normalize_database_url(settings.database_url)
    safe = url
    if "@" in safe:
        try:
            head, tail = safe.split("://", 1)
            creds, host = tail.split("@", 1)
            user = creds.split(":")[0]
            safe = f"{head}://{user}:***@{host}"
        except Exception:
            pass
    print(f"Initializing database: {safe}")
    rebind_engine_from_settings()
    init_db()
    print("Done — tables created (if missing).")


if __name__ == "__main__":
    main()
