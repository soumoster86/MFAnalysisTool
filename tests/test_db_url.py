"""Tests for DATABASE_URL normalization (Supabase / Postgres)."""

from config.db_url import is_supabase_pooler, normalize_database_url


def test_postgres_scheme_to_psycopg():
    u = normalize_database_url(
        "postgresql://postgres:secret@db.abc.supabase.co:5432/postgres"
    )
    assert u.startswith("postgresql+psycopg://")
    assert "sslmode=require" in u
    assert "secret" in u


def test_postgres_short_scheme():
    u = normalize_database_url("postgres://u:p@localhost:5432/db")
    assert u.startswith("postgresql+psycopg://")
    assert "sslmode" not in u  # local host — no forced SSL


def test_pooler_detection():
    assert is_supabase_pooler(
        "postgresql+psycopg://u:p@aws-0-ap-south-1.pooler.supabase.com:6543/postgres"
    )
    assert not is_supabase_pooler(
        "postgresql+psycopg://u:p@db.abc.supabase.co:5432/postgres"
    )


def test_already_psycopg():
    u = normalize_database_url(
        "postgresql+psycopg://postgres:x@db.abc.supabase.co:5432/postgres?sslmode=require"
    )
    assert u.count("sslmode=require") == 1
