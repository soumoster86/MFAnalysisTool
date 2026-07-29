"""Alert API routes (Slice B)."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.deps import get_current_user, get_optional_user
from services.alerts.alert_service import AlertService
from services.alerts.rules import known_alert_types

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])
svc = AlertService()


class HoldingIn(BaseModel):
    amfi_code: Optional[str] = None
    scheme_name: str = ""
    invested_amount: float = 0
    units: float = 0
    sip_amount: float = 0
    market_value: Optional[float] = None
    current_nav: Optional[float] = None
    nav: Optional[float] = None


class EvaluateRequest(BaseModel):
    holdings: list[HoldingIn] = Field(default_factory=list)
    amfi_codes: list[str] = Field(default_factory=list)
    portfolio_id: Optional[int] = None
    use_vault: bool = False
    include_overlap: bool = False
    max_funds: int = Field(default=25, ge=1, le=50)
    persist: bool = True


class RuleUpsert(BaseModel):
    name: str = "Custom rule"
    alert_type: str
    threshold: float
    lookback_days: int = 1
    severity: str = "warning"
    scope: str = "fund"
    enabled: bool = True
    amfi_code: Optional[str] = None
    portfolio_id: Optional[int] = None
    rule_id: Optional[int] = None


@router.get("")
def list_alerts(
    unread_only: bool = False,
    alert_type: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    user: Optional[dict[str, Any]] = Depends(get_optional_user),
) -> dict[str, Any]:
    uid = user["id"] if user else None
    alerts = svc.list_alerts(
        unread_only=unread_only,
        limit=limit,
        user_id=uid,
        alert_type=alert_type,
        severity=severity,
    )
    counts = svc.count_unread(uid)
    return {"count": len(alerts), "unread": counts, "alerts": alerts}


@router.get("/summary")
def alert_summary(
    user: Optional[dict[str, Any]] = Depends(get_optional_user),
) -> dict[str, Any]:
    uid = user["id"] if user else None
    return {"unread": svc.count_unread(uid)}


@router.post("/read-all")
def mark_all_read(
    user: Optional[dict[str, Any]] = Depends(get_optional_user),
) -> dict[str, Any]:
    uid = user["id"] if user else None
    n = svc.mark_all_read(user_id=uid)
    return {"ok": True, "marked": n}


@router.post("/evaluate")
def evaluate(
    body: EvaluateRequest,
    user: Optional[dict[str, Any]] = Depends(get_optional_user),
) -> dict[str, Any]:
    uid = user["id"] if user else None
    if body.use_vault:
        if not uid:
            raise HTTPException(status_code=401, detail="Sign in required for vault evaluate")
        return svc.evaluate_user_vault(
            uid,
            portfolio_id=body.portfolio_id,
            max_funds=body.max_funds,
            include_overlap=body.include_overlap,
        )
    if body.holdings:
        holdings = [h.model_dump() for h in body.holdings]
        return svc.evaluate_portfolio(
            holdings,
            user_id=uid,
            portfolio_id=body.portfolio_id,
            max_funds=body.max_funds,
            include_overlap=body.include_overlap,
            persist=body.persist,
        )
    if body.amfi_codes:
        return svc.evaluate_amfi_codes(
            body.amfi_codes, user_id=uid, max_funds=body.max_funds
        )
    raise HTTPException(
        status_code=400,
        detail="Provide holdings, amfi_codes, or use_vault=true",
    )


@router.get("/rules")
def list_rules(
    user: Optional[dict[str, Any]] = Depends(get_optional_user),
) -> dict[str, Any]:
    uid = user["id"] if user else None
    rules = svc.list_rules(uid)
    return {
        "count": len(rules),
        "types": known_alert_types(),
        "rules": rules,
    }


@router.post("/rules")
def upsert_rule(
    body: RuleUpsert,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return svc.upsert_rule(
            user_id=user["id"],
            name=body.name,
            alert_type=body.alert_type,
            threshold=body.threshold,
            lookback_days=body.lookback_days,
            severity=body.severity,
            scope=body.scope,
            enabled=body.enabled,
            rule_id=body.rule_id,
            amfi_code=body.amfi_code,
            portfolio_id=body.portfolio_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/rules/seed")
def seed_rules(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    n = svc.seed_default_rules(user["id"])
    return {"seeded": n, "rules": svc.list_rules(user["id"])}


@router.post("/rules/{rule_id}/toggle")
def toggle_rule(
    rule_id: int,
    enabled: bool = True,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    ok = svc.set_rule_enabled(rule_id, enabled, user_id=user["id"])
    if not ok:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"ok": True, "id": rule_id, "enabled": enabled}


@router.delete("/rules/{rule_id}")
def delete_rule(
    rule_id: int,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    ok = svc.delete_rule(rule_id, user_id=user["id"])
    if not ok:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"ok": True, "id": rule_id}


@router.post("/{alert_id}/read")
def mark_read(
    alert_id: int,
    user: Optional[dict[str, Any]] = Depends(get_optional_user),
) -> dict[str, Any]:
    uid = user["id"] if user else None
    ok = svc.mark_read(alert_id, user_id=uid)
    if not ok:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"ok": True, "id": alert_id}
