"""Tests for Slice B — real alerts engine + service."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest


@pytest.fixture()
def isolated_db(tmp_path):
    db_path = tmp_path / "test_alerts.db"
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


def _synthetic_nav(days: int = 120, crash_last: bool = True) -> pd.Series:
    idx = pd.date_range(end=datetime.utcnow().date(), periods=days, freq="B")
    rng = np.random.default_rng(42)
    rets = rng.normal(0.0003, 0.008, size=days)
    if crash_last:
        rets[-1] = -0.05  # -5% day
        # build a drawdown stretch
        rets[-15:-5] = -0.01
    nav = 100 * np.cumprod(1 + rets)
    return pd.Series(nav, index=idx, name="nav")


class _FakeFunds:
    def __init__(self, nav: pd.Series):
        self._nav = nav
        self._bulk_skip_persist = True

    def get_nav_history(self, amfi_code, scheme_name=None, years=2.0, force_refresh=False):
        return self._nav.copy()

    def get_holdings(self, amfi_code, scheme_name=None):
        # minimal overlap data
        return pd.DataFrame(
            {
                "security_name": ["HDFC Bank", "Reliance", "Infosys", "TCS"],
                "weight_pct": [8.0, 7.0, 5.0, 4.0],
                "sector": ["Financial", "Energy", "IT", "IT"],
            }
        )


def test_default_rules_catalogue():
    from services.alerts.rules import default_rules, known_alert_types

    rules = default_rules()
    assert len(rules) >= 5
    types = {r.alert_type for r in rules}
    assert "nav_drop" in types
    assert "drawdown" in types
    assert "concentration" in types
    assert set(known_alert_types()) >= types


def test_engine_fires_nav_drop_and_drawdown(isolated_db):
    from services.alerts.engine import AlertEngine
    from services.alerts.rules import RuleSpec

    nav = _synthetic_nav(crash_last=True)
    engine = AlertEngine(fund_service=_FakeFunds(nav))  # type: ignore[arg-type]
    holdings = [
        {
            "amfi_code": "122639",
            "scheme_name": "Test Flexi",
            "invested_amount": 100000,
            "market_value": 85000,  # -15% pnl
            "units": 100,
        }
    ]
    rules = [
        RuleSpec(name="d", alert_type="nav_drop", threshold=-0.03, lookback_days=1, scope="fund"),
        RuleSpec(name="p", alert_type="pnl", threshold=-0.10, lookback_days=0, scope="fund"),
        RuleSpec(
            name="c",
            alert_type="concentration",
            threshold=0.50,
            lookback_days=0,
            scope="portfolio",
            severity="info",
        ),
    ]
    result = engine.evaluate(holdings, rules, include_overlap=False)
    types = {f.alert_type for f in result.fired}
    assert "nav_drop" in types
    assert "pnl" in types
    assert "concentration" in types  # single holding = 100%


def test_alert_rule_exportable():
    """Regression: Streamlit Cloud failed with cannot import name AlertRule."""
    from models.alert import Alert as A1, AlertRule as R1
    from services.alerts.db_models import Alert as A2, AlertRule as R2

    assert A1 is not None and R1 is not None
    assert A2 is not None and R2 is not None
    assert R1.__tablename__ == "alert_rules"
    assert R2.__tablename__ == "alert_rules"


def test_service_persist_and_dedupe(isolated_db, monkeypatch):
    from services.alerts import alert_service as svc_mod
    from services.alerts.alert_service import AlertService
    from services.alerts.engine import AlertEngine
    from services.alerts.rules import RuleSpec

    svc = AlertService()
    nav = _synthetic_nav()

    class Patched(AlertEngine):
        def __init__(self, fund_service=None):
            super().__init__(fund_service=_FakeFunds(nav))  # type: ignore[arg-type]

    monkeypatch.setattr(svc_mod, "_engine_cls", lambda: Patched)

    holdings = [
        {
            "amfi_code": "100001",
            "scheme_name": "Demo Fund",
            "invested_amount": 50000,
            "market_value": 40000,
        }
    ]
    rules = [
        RuleSpec(
            name="nav",
            alert_type="nav_drop",
            threshold=-0.02,
            lookback_days=1,
            scope="fund",
        )
    ]
    out1 = svc.evaluate_portfolio(holdings, rules=rules, include_overlap=False)
    assert out1["alerts_created"] >= 1
    # second run same day should dedupe
    out2 = svc.evaluate_portfolio(holdings, rules=rules, include_overlap=False)
    assert out2["alerts_created"] == 0
    listed = svc.list_alerts(limit=20)
    assert len(listed) >= 1
    aid = listed[0]["id"]
    assert svc.mark_read(aid)
    counts = svc.count_unread()
    assert counts["total"] == 0


def test_seed_and_list_rules(isolated_db):
    from services.alerts.alert_service import AlertService

    svc = AlertService()
    # virtual defaults
    rules = svc.list_rules(user_id=None)
    assert len(rules) >= 5
    n = svc.seed_default_rules(user_id=1)
    assert n >= 5
    n2 = svc.seed_default_rules(user_id=1)
    assert n2 == 0
    persisted = svc.list_rules(user_id=1)
    assert all(r.get("id") for r in persisted)
    rid = persisted[0]["id"]
    assert svc.set_rule_enabled(rid, False, user_id=1)
    row = svc.upsert_rule(
        user_id=1,
        name="Tighter drop",
        alert_type="nav_drop",
        threshold=-0.02,
        lookback_days=1,
        severity="critical",
    )
    assert row["threshold"] == -0.02


def test_evaluate_task_with_holdings(isolated_db, monkeypatch):
    from services.alerts import alert_service as svc_mod
    from services.alerts.engine import AlertEngine
    from workers.tasks import evaluate_alerts

    nav = _synthetic_nav()

    class Patched(AlertEngine):
        def __init__(self, fund_service=None):
            super().__init__(fund_service=_FakeFunds(nav))  # type: ignore[arg-type]

    monkeypatch.setattr(svc_mod, "_engine_cls", lambda: Patched)

    out = evaluate_alerts(
        holdings=[
            {
                "amfi_code": "200002",
                "scheme_name": "Task Fund",
                "invested_amount": 10000,
                "market_value": 9000,
            }
        ],
        include_overlap=False,
        max_funds=5,
    )
    assert out["status"] == "ok"
    assert out.get("alerts_created", 0) >= 1
