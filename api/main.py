"""FastAPI entrypoint — REST API for future React clients & OpenAPI docs."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config.settings import settings
from utils.logging_config import setup_logging

setup_logging(settings.log_level)

app = FastAPI(
    title=settings.app_name,
    description="AI & ML powered Mutual Fund Analysis Platform API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth + portfolio vault (Slice A) + alerts (Slice B)
from api.routes.auth import router as auth_router
from api.routes.portfolios import router as portfolios_router
from api.routes.alerts import router as alerts_router

app.include_router(auth_router)
app.include_router(portfolios_router)
app.include_router(alerts_router)


class PortfolioHoldingIn(BaseModel):
    amfi_code: str
    scheme_name: Optional[str] = None
    invested_amount: float = 0
    units: float = 0
    sip_amount: float = 0


class PortfolioAnalyzeRequest(BaseModel):
    holdings: list[PortfolioHoldingIn]


class GoalPlanRequest(BaseModel):
    age: int = 30
    retirement_age: int = 60
    current_investment: float = 500000
    monthly_sip: float = 20000
    expected_return: float = 0.12
    expected_inflation: float = 0.06
    goal_amount: Optional[float] = None
    return_volatility: float = 0.15
    n_simulations: int = 1000


class RecommendRequest(BaseModel):
    risk_appetite: str = "Moderate"
    investment_horizon: int = 7
    monthly_sip: float = 10000
    age: int = 30
    goals: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    context_extra: Optional[str] = None


class OptimizeRequest(BaseModel):
    amfi_codes: list[str] = Field(min_length=2, max_length=15)
    method: str = "max_sharpe"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}


@app.get("/api/v1/funds/search")
def search_funds(
    q: str = Query("", description="Scheme name or AMFI code"),
    category: Optional[str] = None,
    limit: int = 30,
) -> dict[str, Any]:
    from services.data.fund_service import FundService

    df = FundService().search_funds(q, category=category, limit=limit)
    return {"count": len(df), "results": df.fillna("").to_dict(orient="records")}


@app.get("/api/v1/funds/{amfi_code}")
def fund_detail(amfi_code: str) -> dict[str, Any]:
    from services.data.fund_service import FundService

    try:
        data = FundService().compute_fund_analytics(amfi_code)
        nav = data.pop("nav", None)
        if nav is not None and hasattr(nav, "index"):
            data["nav_summary"] = {
                "points": len(nav),
                "start": str(nav.index.min().date()) if len(nav) else None,
                "end": str(nav.index.max().date()) if len(nav) else None,
                "source": getattr(nav, "attrs", {}).get("source"),
            }
        if "holdings" in data and hasattr(data["holdings"], "to_dict"):
            data["holdings"] = data["holdings"].to_dict(orient="records")
        return data
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/funds/{amfi_code}/nav")
def fund_nav_history(amfi_code: str, years: float = 5.0, force: bool = False) -> dict[str, Any]:
    """Real historical NAV from mfapi.in (TigZig fallback)."""
    from services.data.fund_service import FundService

    try:
        svc = FundService()
        nav = svc.get_nav_history(amfi_code, years=years, force_refresh=force)
        return {
            "amfi_code": amfi_code,
            "source": svc.get_nav_source(amfi_code) or nav.attrs.get("source"),
            "points": len(nav),
            "start": str(nav.index.min().date()) if len(nav) else None,
            "end": str(nav.index.max().date()) if len(nav) else None,
            "latest_nav": float(nav.iloc[-1]) if len(nav) else None,
            "series": [
                {"date": str(pd_ts.date()), "nav": float(v)}
                for pd_ts, v in nav.items()
            ]
            if len(nav) <= 5000
            else None,
            "note": "series omitted when >5000 points; use years filter"
            if len(nav) > 5000
            else None,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/funds/{amfi_code}/holdings")
def fund_holdings(amfi_code: str, force: bool = False) -> dict[str, Any]:
    """Portfolio holdings from Groww (sample fallback if unavailable)."""
    from services.data.fund_service import FundService

    try:
        svc = FundService()
        meta = svc.get_fund_meta(amfi_code)
        df = svc.get_holdings(amfi_code, meta.get("scheme_name"), force_refresh=force)
        return {
            "amfi_code": amfi_code,
            "source": svc.get_holdings_source(amfi_code),
            "count": len(df),
            "holdings": df.fillna("").to_dict(orient="records"),
            "enriched_meta": svc.get_enriched_meta(amfi_code, meta.get("scheme_name")),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/funds/{amfi_code}/xray")
def fund_xray(amfi_code: str) -> dict[str, Any]:
    from analytics.xray import FundXRay
    from services.data.fund_service import FundService

    svc = FundService()
    a = svc.compute_fund_analytics(amfi_code)
    report = FundXRay().analyze(
        scheme_name=a["meta"].get("scheme_name") or amfi_code,
        nav=a["nav"],
        holdings=a["holdings"],
        expense_ratio=a.get("expense_ratio"),
        manager_tenure=a.get("manager_tenure"),
        aum_cr=a.get("aum_cr"),
        category=a["meta"].get("category"),
    )
    return report.to_dict()


@app.post("/api/v1/portfolio/analyze")
def portfolio_analyze(body: PortfolioAnalyzeRequest) -> dict[str, Any]:
    from services.portfolio.analyzer import PortfolioAnalyzerService

    result = PortfolioAnalyzerService().analyze([h.model_dump() for h in body.holdings])
    d = result.to_dict()
    return d


@app.post("/api/v1/goals/plan")
def goal_plan(body: GoalPlanRequest) -> dict[str, Any]:
    from analytics.goal_planner import GoalPlanner

    res = GoalPlanner().plan(**body.model_dump())
    d = res.to_dict()
    d.pop("simulation_paths_sample", None)  # keep payload light
    return d


@app.post("/api/v1/recommend")
def recommend(body: RecommendRequest) -> dict[str, Any]:
    from ml.recommender import RecommendationEngine

    return RecommendationEngine().recommend(**body.model_dump()).to_dict()


@app.post("/api/v1/optimize")
def optimize(body: OptimizeRequest) -> dict[str, Any]:
    import pandas as pd

    from analytics.optimizer import PortfolioOptimizer
    from services.data.fund_service import FundService

    svc = FundService()
    series = {}
    for code in body.amfi_codes:
        meta = svc.get_fund_meta(code)
        nav = svc.get_nav_history(code, meta.get("scheme_name"), meta.get("nav"))
        series[meta.get("scheme_name") or code] = nav.pct_change()
    rets = pd.DataFrame(series).dropna(how="all").fillna(0)
    opt = PortfolioOptimizer()
    method = body.method.lower()
    if method == "min_variance":
        res = opt.min_variance(rets)
    elif method == "risk_parity":
        res = opt.risk_parity(rets)
    elif method == "black_litterman":
        res = opt.black_litterman_simple(rets)
    else:
        res = opt.max_sharpe(rets)
    return res.to_dict()


@app.post("/api/v1/chat")
def chat(body: ChatRequest) -> dict[str, Any]:
    from services.ai.assistant import FinancialAssistant

    assistant = FinancialAssistant()
    ctx = assistant.build_context(extra=body.context_extra)
    return assistant.chat(body.message, context=ctx)


@app.post("/api/v1/admin/sync-amfi")
def sync_amfi(limit: int = 300, force: bool = False) -> dict[str, Any]:
    from services.data.fund_service import FundService

    n = FundService().sync_amfi_to_db(limit=limit, force=force)
    return {"synced": n}


@app.post("/api/v1/portfolio/import-cas")
async def import_cas(
    file: UploadFile = File(...),
    include_soa: bool = True,
    include_demat: bool = True,
    merge_duplicates: bool = True,
    min_match_score: float = 0.45,
) -> dict[str, Any]:
    """
    Upload MFCentral CAS Summary PDF and return mapped portfolio holdings.

    PAN is returned masked only. Does not persist the PDF.
    """
    from services.portfolio.import_service import PortfolioImportService

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Upload a .pdf CAS Summary file")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    try:
        result = PortfolioImportService().import_cas_pdf(
            data,
            filename=file.filename,
            include_soa=include_soa,
            include_demat=include_demat,
            merge_duplicates=merge_duplicates,
            min_match_score=min_match_score,
        )
        return result.to_dict()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
