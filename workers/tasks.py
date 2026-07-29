"""Background tasks: AMFI refresh, alert evaluation (Celery stubs)."""

from __future__ import annotations

from typing import Any

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
def evaluate_alerts(amfi_codes: list[str] | None = None) -> dict[str, Any]:
    from services.alerts.alert_service import AlertService
    from services.data.fund_service import FundService

    funds = FundService()
    alerts = AlertService()
    created = 0
    codes = amfi_codes or []
    for code in codes:
        try:
            nav = funds.get_nav_history(code)
            if len(nav) < 2:
                continue
            daily = float(nav.iloc[-1] / nav.iloc[-2] - 1)
            peak = nav.cummax()
            dd = float((nav.iloc[-1] - peak.iloc[-1]) / peak.iloc[-1]) if peak.iloc[-1] else 0
            meta = funds.get_fund_meta(code)
            created += len(
                alerts.evaluate_nav_alerts(
                    meta.get("scheme_name") or code, code, daily, dd
                )
            )
        except Exception as exc:
            logger.warning("Alert eval failed for {}: {}", code, exc)
    return {"status": "ok", "alerts_created": created}


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
