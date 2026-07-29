"""Portfolio vault API routes."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.deps import get_current_user
from services.portfolio.vault_service import PortfolioVaultService, VaultError

router = APIRouter(prefix="/api/v1/portfolios", tags=["portfolios"])
vault = PortfolioVaultService()


class HoldingIn(BaseModel):
    amfi_code: Optional[str] = None
    scheme_name: str = ""
    invested_amount: float = 0
    units: float = 0
    sip_amount: float = 0
    market_value: Optional[float] = None
    current_nav: Optional[float] = None
    nav: Optional[float] = None
    folio: Optional[str] = None
    holding_type: Optional[str] = None


class PortfolioCreate(BaseModel):
    name: str = "My Portfolio"
    holdings: list[HoldingIn] = Field(default_factory=list)
    source: str = "manual"
    description: Optional[str] = None
    as_of_date: Optional[str] = None
    set_default: bool = True


class PortfolioUpdate(BaseModel):
    name: Optional[str] = None
    holdings: Optional[list[HoldingIn]] = None
    description: Optional[str] = None
    as_of_date: Optional[str] = None
    source: Optional[str] = None
    set_default: Optional[bool] = None


@router.get("")
def list_portfolios(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    items = vault.list_portfolios(user["id"])
    return {"count": len(items), "portfolios": items}


@router.post("")
def create_portfolio(
    body: PortfolioCreate, user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, Any]:
    try:
        return vault.create_portfolio(
            user["id"],
            body.name,
            [h.model_dump() for h in body.holdings],
            source=body.source,
            description=body.description,
            as_of_date=body.as_of_date,
            set_default=body.set_default,
        )
    except VaultError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/default")
def get_default(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    p = vault.get_default_portfolio(user["id"])
    if not p:
        raise HTTPException(status_code=404, detail="No portfolios yet")
    return p


@router.get("/{portfolio_id}")
def get_portfolio(
    portfolio_id: int, user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, Any]:
    try:
        return vault.get_portfolio(portfolio_id, user["id"])
    except VaultError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{portfolio_id}")
def update_portfolio(
    portfolio_id: int,
    body: PortfolioUpdate,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        holdings = (
            [h.model_dump() for h in body.holdings] if body.holdings is not None else None
        )
        return vault.update_portfolio(
            portfolio_id,
            user["id"],
            name=body.name,
            holdings=holdings,
            description=body.description,
            as_of_date=body.as_of_date,
            source=body.source,
            set_default=body.set_default,
        )
    except VaultError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{portfolio_id}")
def delete_portfolio(
    portfolio_id: int, user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, Any]:
    ok = vault.delete_portfolio(portfolio_id, user["id"])
    if not ok:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return {"deleted": True, "id": portfolio_id}
