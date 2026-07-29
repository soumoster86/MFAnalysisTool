"""Normalize DATABASE_URL for SQLAlchemy + Neon / Supabase / Postgres."""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


def normalize_database_url(url: str) -> str:
    """
    Convert common Postgres URLs into SQLAlchemy + psycopg form.

    Accepts:
      - postgresql://...
      - postgres://...
      - postgresql+psycopg://...
      - Neon / Supabase dashboard URIs
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

    # Managed cloud Postgres requires SSL
    if _requires_ssl(u) and "sslmode=" not in u:
        u = _add_query_param(u, "sslmode", "require")

    # Neon often works best with channel_binding=require disabled on some clients;
    # leave URL as Neon provides it if already present.
    return u


def _requires_ssl(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(
        x in host
        for x in (
            "neon.tech",
            "neon.database",
            "supabase.co",
            "supabase.com",
            "amazonaws.com",  # many managed PG hosts
            "azure.com",
            "rds.amazonaws.com",
        )
    )


def _is_neon(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return "neon.tech" in host or "neon.database" in host


def is_supabase_pooler(url: str) -> bool:
    """Transaction pooler hosts that need prepare_threshold=None."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    port = parsed.port
    if "pooler.supabase" in host:
        return True
    if port == 6543 and ("supabase.co" in host or "supabase.com" in host):
        return True
    # Neon pooled endpoint (-pooler in hostname)
    if _is_neon(url) and ("-pooler" in host or port == 6543):
        return True
    return False


# Back-compat alias used by database.session
is_serverless_pooler = is_supabase_pooler


def _add_query_param(url: str, key: str, value: str) -> str:
    parsed = urlparse(url)
    q = parse_qs(parsed.query, keep_blank_values=True)
    q[key] = [value]
    flat = []
    for k, vals in q.items():
        for v in vals:
            flat.append((k, v))
    new_query = urlencode(flat)
    return urlunparse(parsed._replace(query=new_query))
