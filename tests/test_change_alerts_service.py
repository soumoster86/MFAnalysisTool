"""AlertService change-detection flow: snapshot storage, baseline, dedupe."""

from __future__ import annotations

import pandas as pd
import pytest


@pytest.fixture()
def isolated_db(tmp_path):
    db_path = tmp_path / "test_change_alerts.db"
    url = f"sqlite:///{db_path.as_posix()}"

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from database import session as session_mod

    engine = create_engine(url, connect_args={"check_same_thread": False})
    session_mod.engine = engine
    session_mod.SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    import models  # noqa: F401
    import services.alerts.db_models  # noqa: F401

    session_mod.Base.metadata.drop_all(bind=engine)
    session_mod.Base.metadata.create_all(bind=engine)
    yield url


class _FakeFundService:
    """Serves a mutable meta/holdings pair so a 'change' can be staged."""

    def __init__(self):
        self.meta = {
            "scheme_name": "Test Fund",
            "fund_manager": "A. Manager",
            "expense_ratio": 1.00,
            "category": "Equity",
            "subcategory": "Flexi Cap",
            "benchmark": "NIFTY 500 TRI",
            "riskometer": "High",
            "aum_cr": 5000.0,
        }
        self.holdings = pd.DataFrame(
            [
                {"security_name": "HDFC Bank", "weight_pct": 8.0, "sector": "Financials"},
                {"security_name": "Infosys", "weight_pct": 6.0, "sector": "IT"},
            ]
        )

    def get_fund_meta(self, code, enrich=False):
        return dict(self.meta)

    def get_holdings(self, code, name=None):
        return self.holdings.copy()

    def get_holdings_source(self, code):
        return "groww"

    def get_nav_source(self, code):
        return "mfapi"

    def get_nav_history(self, code, scheme_name=None, years=1.0):
        raise RuntimeError("no NAV in this test")


@pytest.fixture()
def service(isolated_db):
    from services.alerts.alert_service import AlertService

    svc = AlertService()
    svc._funds = _FakeFundService()
    return svc


HOLDINGS = [{"amfi_code": "100", "scheme_name": "Test Fund"}]


def test_first_run_records_a_baseline_and_fires_nothing(service):
    out = service.detect_fund_changes(HOLDINGS)
    assert out["baselines"] == 1
    assert out["alerts_created"] == 0
    assert service.latest_snapshot("100") is not None


def test_second_run_with_no_change_fires_nothing(service):
    service.detect_fund_changes(HOLDINGS)
    out = service.detect_fund_changes(HOLDINGS)
    assert out["baselines"] == 0
    assert out["alerts_created"] == 0


def test_manager_change_between_runs_creates_an_alert(service):
    service.detect_fund_changes(HOLDINGS)
    service._funds.meta["fund_manager"] = "B. Newperson"

    out = service.detect_fund_changes(HOLDINGS)
    assert out["alerts_created"] == 1

    alerts = service.list_alerts(alert_type="manager_change", limit=10)
    assert len(alerts) == 1
    assert "B. Newperson" in alerts[0]["message"]
    assert alerts[0]["severity"] == "critical"


def test_same_change_does_not_alert_twice(service):
    # Fingerprint is the change itself, not the date — a manager change must
    # alert once, not on every scan.
    service.detect_fund_changes(HOLDINGS)
    service._funds.meta["fund_manager"] = "B. Newperson"
    first = service.detect_fund_changes(HOLDINGS)
    second = service.detect_fund_changes(HOLDINGS)

    assert first["alerts_created"] == 1
    assert second["alerts_created"] == 0
    assert len(service.list_alerts(alert_type="manager_change", limit=10)) == 1


def test_a_further_change_alerts_again(service):
    service.detect_fund_changes(HOLDINGS)
    service._funds.meta["fund_manager"] = "B. Newperson"
    service.detect_fund_changes(HOLDINGS)
    service._funds.meta["fund_manager"] = "C. Third"
    out = service.detect_fund_changes(HOLDINGS)

    assert out["alerts_created"] == 1
    assert len(service.list_alerts(alert_type="manager_change", limit=10)) == 2


def test_expense_ratio_change_is_persisted_with_metric_and_threshold(service):
    service.detect_fund_changes(HOLDINGS)
    service._funds.meta["expense_ratio"] = 1.35
    service.detect_fund_changes(HOLDINGS)

    alerts = service.list_alerts(alert_type="expense_ratio_change", limit=10)
    assert len(alerts) == 1
    assert alerts[0]["metric_value"] == pytest.approx(0.35)
    assert alerts[0]["threshold"] == pytest.approx(0.10)


def test_holdings_change_fires_when_the_portfolio_turns_over(service):
    service.detect_fund_changes(HOLDINGS)
    service._funds.holdings = pd.DataFrame(
        [
            {"security_name": "Reliance", "weight_pct": 8.0, "sector": "Energy"},
            {"security_name": "Infosys", "weight_pct": 6.0, "sector": "IT"},
        ]
    )
    service.detect_fund_changes(HOLDINGS)

    alerts = service.list_alerts(alert_type="holdings_change", limit=10)
    assert len(alerts) == 1


def test_dry_run_does_not_persist(service):
    service.detect_fund_changes(HOLDINGS)
    service._funds.meta["fund_manager"] = "B. Newperson"
    out = service.detect_fund_changes(HOLDINGS, persist=False)

    assert out["alerts_created"] == 1
    assert service.list_alerts(alert_type="manager_change", limit=10) == []


def test_change_rules_are_excluded_from_nav_evaluation(service):
    # detect_fund_changes owns them; evaluate_portfolio must not count them.
    out = service.evaluate_portfolio([], persist=False)
    assert out["checked_rules"] == len(
        [s for s in service.get_rule_specs(None) if s.alert_type in
         ("nav_drop", "period_return", "drawdown", "pnl", "concentration", "overlap")]
    )


def test_seeded_defaults_cover_every_roadmap_change_trigger(service):
    from services.alerts.rules import CHANGE_ALERT_TYPES

    seeded = {s.alert_type for s in service.get_rule_specs(None)}
    for atype in CHANGE_ALERT_TYPES:
        assert atype in seeded, f"no default rule seeds {atype}"


def _seed_legacy_rules_only(service):
    """Recreate an install seeded before change detection shipped."""
    from database import session as db_session
    from services.alerts.db_models import AlertRule

    with db_session.SessionLocal() as db:
        for atype in ("nav_drop", "drawdown", "pnl", "concentration", "overlap"):
            db.add(AlertRule(user_id=None, name=f"legacy {atype}", alert_type=atype))
        db.commit()


def test_new_rule_types_reach_installs_seeded_before_they_existed(service):
    # get_rule_specs used to return stored rules OR defaults, never both, so a
    # pre-existing install would never see a newly shipped alert type.
    _seed_legacy_rules_only(service)
    from services.alerts.rules import CHANGE_ALERT_TYPES

    types = {s.alert_type for s in service.get_rule_specs(None)}
    for atype in CHANGE_ALERT_TYPES:
        assert atype in types, f"{atype} did not reach a legacy install"


def test_change_detection_works_on_a_legacy_install(service):
    _seed_legacy_rules_only(service)
    service.detect_fund_changes(HOLDINGS)
    service._funds.meta["fund_manager"] = "B. Newperson"
    out = service.detect_fund_changes(HOLDINGS)
    assert out["alerts_created"] == 1


def test_a_deliberately_disabled_rule_is_not_resurrected_by_defaults(service):
    from database import session as db_session
    from services.alerts.db_models import AlertRule

    with db_session.SessionLocal() as db:
        db.add(
            AlertRule(
                user_id=None,
                name="off",
                alert_type="manager_change",
                enabled=False,
            )
        )
        db.add(AlertRule(user_id=None, name="nav", alert_type="nav_drop"))
        db.commit()

    types = {s.alert_type for s in service.get_rule_specs(None)}
    assert "manager_change" not in types


def test_disabled_change_rule_stops_that_alert_firing(service):
    from database import session as db_session
    from services.alerts.db_models import AlertRule

    with db_session.SessionLocal() as db:
        db.add(
            AlertRule(
                user_id=None, name="off", alert_type="manager_change", enabled=False
            )
        )
        db.commit()

    service.detect_fund_changes(HOLDINGS)
    service._funds.meta["fund_manager"] = "B. Newperson"
    out = service.detect_fund_changes(HOLDINGS)
    assert out["alerts_created"] == 0


def test_no_change_rules_at_all_reports_why(service):
    from database import session as db_session
    from services.alerts.db_models import AlertRule
    from services.alerts.rules import CHANGE_ALERT_TYPES

    with db_session.SessionLocal() as db:
        for atype in CHANGE_ALERT_TYPES:
            db.add(AlertRule(user_id=None, name=atype, alert_type=atype, enabled=False))
        db.commit()

    out = service.detect_fund_changes(HOLDINGS)
    # A bare "checked 0 funds" hides the reason from the user.
    assert "message" in out
    assert out["alerts_created"] == 0
