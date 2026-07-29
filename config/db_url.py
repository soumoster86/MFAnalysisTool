"""Normalize DATABASE_URL for SQLAlchemy + Supabase / Postgres."""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


def normalize_database_url(url: str) -> str:
    """
    Convert common Postgres URLs into SQLAlchemy + psycopg form.

    Accepts:
      - postgresql://...
      - postgres://...
      - postgresql+psycopg://...
      - Supabase URI from dashboard (with or without sslmode)
    """
    if not url:
        return url
    u = url.strip().strip('"').strip("'")

    # Heroku-style scheme
    if u.startswith("postgres://"):
        u = "postgresql://" + u[len("postgres://") :]

    # Prefer psycopg3 driver for SQLAlchemy 2
    if u.startswith("postgresql://") and "+psycopg" not in u and "+psycopg2" not in u:
        u = "postgresql+psycopg://" + u[len("postgresql://") :]

    # Supabase requires SSL; add if missing
    if _is_supabase(u) and "sslmode=" not in u:
        u = _add_query_param(u, "sslmode", "require")

    return u


def _is_supabase(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return "supabase.co" in host or "supabase.com" in host


def is_supabase_pooler(url: str) -> bool:
    """Transaction pooler (port 6543) needs special psycopg settings."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    port = parsed.port
    if "pooler.supabase" in host:
        return True
    if port == 6543 and _is_supabase(url):
        return True
    return False


def _add_query_param(url: str, key: str, value: str) -> str:
    parsed = urlparse(url)
    q = parse_qs(parsed.query, keep_blank_values=True)
    q[key] = [value]
    # flatten
    flat = []
    for k, vals in q.items():
        for v in vals:
            flat.append((k, v))
    new_query = urlencode(flat)
    return urlunparse(parsed._replace(query=new_query))
