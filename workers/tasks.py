"""Background tasks: AMFI refresh, alert evaluation (Celery-ready)."""

from __future__ import annotations

from typing import Any, Optional

from utils.logging_config import get_logger

logger = get_logger(__name__)

try:
    from workers.celery_app import celery_app
except Exception:  # pragma: no cover
    celery_app = None


def _task(name: str):
    """Decorator that works with or without Celery."""

    def wrapper(fn):
        if celery_app is not None:
            return celery_app.task(name=name)(fn)
        fn.delay = lambda *a, **k: fn(*a, **k)  # type: ignore[attr-defined]
        return fn

    return wrapper


@_task("workers.tasks.refresh_amfi")
def refresh_amfi(force: bool = True) -> dict[str, Any]:
    from services.data.fund_service import FundService

    svc = FundService()
    n = svc.sync_amfi_to_db(limit=500, force=force)
    logger.info("AMFI refresh complete: {} funds", n)
    return {"status": "ok", "funds_synced": n}


@_task("workers.tasks.refresh_nav_history")
def refresh_nav_history(amfi_codes: list[str] | None = None, years: float = 5.0) -> dict[str, Any]:
    """Pull real historical NAV (+ holdings) for a list of schemes."""
    from services.data.fund_service import FundService

    svc = FundService()
    codes = amfi_codes or []
    results = []
    for code in codes:
        try:
            info = svc.prefetch_fund(code, years=years, force=True)
            results.append(info)
        except Exception as exc:
            results.append({"amfi_code": code, "error": str(exc)})
    return {"status": "ok", "results": results}


@_task("workers.tasks.evaluate_alerts")
def evaluate_alerts(
    amfi_codes: list[str] | None = None,
    holdings: list[dict[str, Any]] | None = None,
    user_id: Optional[int] = None,
    portfolio_id: Optional[int] = None,
    include_overlap: bool = False,
    max_funds: int = 25,
) -> dict[str, Any]:
    """
    Slice B: evaluate real alert rules.

    Prefer `holdings` (session/CAS/vault rows). Fall back to amfi_codes only
    (NAV/drawdown rules). Vault path: pass user_id (+ optional portfolio_id).
    """
    from services.alerts.alert_service import AlertService

    alerts = AlertService()

    # Full vault scan for a user
    if user_id is not None and holdings is None and not amfi_codes:
        out = alerts.evaluate_user_vault(
            user_id,
            portfolio_id=portfolio_id,
            max_funds=max_funds,
            include_overlap=include_overlap,
        )
        logger.info(
            "Vault alert eval user={} created={}",
            user_id,
            out.get("alerts_created"),
        )
        return out

    if holdings:
        out = alerts.evaluate_portfolio(
            holdings,
            user_id=user_id,
            portfolio_id=portfolio_id,
            max_funds=max_funds,
            include_overlap=include_overlap,
        )
        logger.info("Holdings alert eval created={}", out.get("alerts_created"))
        return out

    codes = amfi_codes or []
    if not codes:
        return {"status": "ok", "alerts_created": 0, "message": "No codes or holdings"}

    out = alerts.evaluate_amfi_codes(codes, user_id=user_id, max_funds=max_funds)
    logger.info("AMFI-code alert eval created={}", out.get("alerts_created"))
    return out


@_task("workers.tasks.detect_fund_changes")
def detect_fund_changes(
    amfi_codes: list[str] | None = None,
    holdings: list[dict[str, Any]] | None = None,
    user_id: Optional[int] = None,
    portfolio_id: Optional[int] = None,
    max_funds: int = 25,
) -> dict[str, Any]:
    """Snapshot funds and alert on manager / TER / category / benchmark /
    holdings / sector / risk changes.

    Meant to run on a slow cadence (daily). Fund attributes change on the
    order of weeks, and each run costs one meta + holdings fetch per fund.
    """
    from services.alerts.alert_service import AlertService

    rows = holdings or [
        {"amfi_code": str(c), "scheme_name": str(c)} for c in (amfi_codes or [])
    ]
    if not rows:
        return {"status": "ok", "alerts_created": 0, "message": "No codes or holdings"}

    out = AlertService().detect_fund_changes(
        rows,
        user_id=user_id,
        portfolio_id=portfolio_id,
        max_funds=max_funds,
    )
    logger.info(
        "Change detection created={} baselines={} funds={}",
        out.get("alerts_created"),
        out.get("baselines"),
        out.get("checked_funds"),
    )
    return out


@_task("workers.tasks.detect_all_vault_changes")
def detect_all_vault_changes(max_users: int = 50, max_funds: int = 15) -> dict[str, Any]:
    """Beat task: run change detection over recent users' default portfolios."""
    from database import session as db_session
    from models.user import User
    from services.alerts.alert_service import AlertService
    from services.portfolio.vault_service import PortfolioVaultService

    db_session.init_db()
    alerts = AlertService()
    vault = PortfolioVaultService()
    scanned = 0
    created = 0
    baselines = 0
    errors: list[str] = []

    with db_session.SessionLocal() as db:
        users = (
            db.query(User)
            .filter(User.is_active.is_(True))
            .order_by(User.id.desc())
            .limit(max_users)
            .all()
        )
        user_ids = [u.id for u in users]

    for uid in user_ids:
        try:
            portfolios = vault.list_portfolios(uid)
            if not portfolios:
                continue
            target = next((p for p in portfolios if p.get("is_default")), portfolios[0])
            detail = vault.get_portfolio(target["id"], uid)
            rows = vault.holdings_for_analyzer(detail)
            if not rows:
                continue
            out = alerts.detect_fund_changes(
                rows, user_id=uid, portfolio_id=target["id"], max_funds=max_funds
            )
            scanned += 1
            created += out.get("alerts_created", 0)
            baselines += out.get("baselines", 0)
        except Exception as exc:
            errors.append(f"user {uid}: {exc}")
            logger.warning("Change detection beat failed user={}: {}", uid, exc)

    return {
        "status": "ok",
        "users_scanned": scanned,
        "alerts_created": created,
        "baselines": baselines,
        "errors": errors[:10],
    }


@_task("workers.tasks.evaluate_all_vault_alerts")
def evaluate_all_vault_alerts(
    max_users: int = 50,
    max_funds: int = 15,
) -> dict[str, Any]:
    """
    Scheduled beat task: evaluate default vault portfolios for recent users.

    Requires Redis + Celery worker when celery_enabled=true; otherwise runs inline.
    """
    from models.user import User
    from database import session as db_session
    from services.alerts.alert_service import AlertService

    db_session.init_db()
    alerts = AlertService()
    created = 0
    scanned = 0
    errors: list[str] = []

    with db_session.SessionLocal() as db:
        users = (
            db.query(User)
            .filter(User.is_active.is_(True))
            .order_by(User.id.desc())
            .limit(max_users)
            .all()
        )
        user_ids = [u.id for u in users]

    for uid in user_ids:
        try:
            out = alerts.evaluate_user_vault(
                uid,
                max_funds=max_funds,
                include_overlap=False,
            )
            created += int(out.get("alerts_created") or 0)
            scanned += 1
        except Exception as exc:
            errors.append(f"user {uid}: {exc}")
            logger.warning("Vault alert beat failed user={}: {}", uid, exc)

    return {
        "status": "ok",
        "users_scanned": scanned,
        "alerts_created": created,
        "errors": errors[:20],
    }


@_task("workers.tasks.train_fund_model")
def train_fund_model(amfi_code: str) -> dict[str, Any]:
    from ml.feature_engineering import FeatureEngineer
    from ml.model_trainer import ModelTrainer
    from services.data.fund_service import FundService

    svc = FundService()
    nav = svc.get_nav_history(amfi_code)
    bench = svc.yf.get_benchmark("NIFTY 50")
    fe = FeatureEngineer()
    feat = fe.from_nav(nav, bench)
    X, y = fe.make_supervised(feat, "fwd_ret_63")
    result = ModelTrainer().compare(X, y, "fwd_ret_63")
    return result.to_dict()
