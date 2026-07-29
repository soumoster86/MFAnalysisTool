"""Tests for Slice A — auth + portfolio vault."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture()
def isolated_db(monkeypatch, tmp_path):
    """Point app DB at a temp SQLite file and re-init tables."""
    db_path = tmp_path / "test_vault.db"
    url = f"sqlite:///{db_path.as_posix()}"

    from database import session as session_mod
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(url, connect_args={"check_same_thread": False})
    session_mod.engine = engine
    session_mod.SessionLocal = sessionmaker(
        bind=engine, autocommit=False, autoflush=False
    )

    import models  # noqa: F401

    session_mod.Base.metadata.drop_all(bind=engine)
    session_mod.Base.metadata.create_all(bind=engine)
    yield url


def test_register_login(isolated_db):
    from services.auth.auth_service import AuthError, AuthService

    auth = AuthService()
    user = auth.register("alice@example.com", "secret12", "Alice")
    assert user["email"] == "alice@example.com"
    assert user["id"]

    with pytest.raises(AuthError):
        auth.register("alice@example.com", "secret12")

    tok = auth.authenticate("alice@example.com", "secret12")
    assert tok["access_token"]
    assert tok["user"]["email"] == "alice@example.com"

    me = auth.get_user_from_token(tok["access_token"])
    assert me["id"] == user["id"]

    with pytest.raises(AuthError):
        auth.authenticate("alice@example.com", "wrong")


def test_portfolio_vault_crud(isolated_db):
    from services.auth.auth_service import AuthService
    from services.portfolio.vault_service import PortfolioVaultService

    auth = AuthService()
    user = auth.register("bob@example.com", "secret12", "Bob")
    vault = PortfolioVaultService()

    holdings = [
        {
            "amfi_code": "122639",
            "scheme_name": "Parag Parikh Flexi Cap",
            "units": 10,
            "invested_amount": 5000,
            "market_value": 9000,
            "current_nav": 90,
        },
        {
            "amfi_code": "120503",
            "scheme_name": "Demo Flexi",
            "units": 5,
            "invested_amount": 2000,
            "market_value": 2500,
            "current_nav": 50,
        },
    ]
    created = vault.create_portfolio(
        user["id"],
        "CAS 2026-07-29",
        holdings,
        source="cas_import",
        as_of_date="29-Jul-2026",
        set_default=True,
    )
    assert created["id"]
    assert created["holdings_count"] == 2
    assert created["total_market_value"] == 11500

    listed = vault.list_portfolios(user["id"])
    assert len(listed) == 1

    loaded = vault.get_portfolio(created["id"], user["id"])
    assert len(loaded["holdings"]) == 2

    rows = vault.holdings_for_analyzer(loaded)
    assert rows[0]["amfi_code"] == "122639"
    assert rows[0]["market_value"] == 9000

    updated = vault.update_portfolio(
        created["id"],
        user["id"],
        holdings=holdings[:1],
        name="CAS slim",
    )
    assert updated["name"] == "CAS slim"
    assert updated["holdings_count"] == 1

    default = vault.get_default_portfolio(user["id"])
    assert default and default["id"] == created["id"]

    assert vault.delete_portfolio(created["id"], user["id"]) is True
    assert vault.list_portfolios(user["id"]) == []


def test_auth_api(isolated_db):
    from fastapi.testclient import TestClient

    from api.main import app

    client = TestClient(app)
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "api@example.com", "password": "secret12", "full_name": "API"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    token = body["access_token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "api@example.com"

    create = client.post(
        "/api/v1/portfolios",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "API Portfolio",
            "source": "manual",
            "holdings": [
                {
                    "amfi_code": "122639",
                    "scheme_name": "PPFAS",
                    "units": 1,
                    "invested_amount": 100,
                    "market_value": 110,
                }
            ],
        },
    )
    assert create.status_code == 200, create.text
    pid = create.json()["id"]

    lst = client.get("/api/v1/portfolios", headers={"Authorization": f"Bearer {token}"})
    assert lst.status_code == 200
    assert lst.json()["count"] >= 1

    got = client.get(f"/api/v1/portfolios/{pid}", headers={"Authorization": f"Bearer {token}"})
    assert got.status_code == 200
    assert len(got.json()["holdings"]) == 1
