"""Shared Streamlit session-state helpers: auth, vault, analysis cache."""

from __future__ import annotations

from typing import Any, Callable, Optional

import streamlit as st

from services.auth.auth_service import AuthError, AuthService, get_auth_service
from services.data.fund_service import FundService
from services.portfolio.analyzer import (
    PortfolioAnalysis,
    PortfolioAnalyzerService,
    holdings_fingerprint,
)
from services.portfolio.vault_service import PortfolioVaultService


# ---------------------------------------------------------------------------
# Core services
# ---------------------------------------------------------------------------

def get_fund_service() -> FundService:
    if "fund_service" not in st.session_state:
        st.session_state.fund_service = FundService()
        st.session_state.fund_service._bulk_skip_persist = True  # type: ignore[attr-defined]
    return st.session_state.fund_service


def get_portfolio_analyzer() -> PortfolioAnalyzerService:
    if "portfolio_analyzer" not in st.session_state:
        st.session_state.portfolio_analyzer = PortfolioAnalyzerService(get_fund_service())
    return st.session_state.portfolio_analyzer


def get_vault() -> PortfolioVaultService:
    if "vault_service" not in st.session_state:
        st.session_state.vault_service = PortfolioVaultService()
    return st.session_state.vault_service


def get_auth() -> AuthService:
    return get_auth_service()


# ---------------------------------------------------------------------------
# Auth session
# ---------------------------------------------------------------------------

def is_logged_in() -> bool:
    return bool(st.session_state.get("auth_user") and st.session_state.get("auth_token"))


def get_current_user() -> Optional[dict[str, Any]]:
    return st.session_state.get("auth_user")


def get_auth_token() -> Optional[str]:
    return st.session_state.get("auth_token")


def login_user(email: str, password: str) -> dict[str, Any]:
    result = get_auth().authenticate(email, password)
    st.session_state["auth_token"] = result["access_token"]
    st.session_state["auth_user"] = result["user"]
    # Auto-load default portfolio if session is still demo/empty-ish
    _maybe_autoload_default()
    return result


def register_user(
    email: str, password: str, full_name: Optional[str] = None
) -> dict[str, Any]:
    get_auth().register(email, password, full_name)
    return login_user(email, password)


def clear_auth() -> None:
    st.session_state.pop("auth_token", None)
    st.session_state.pop("auth_user", None)
    st.session_state.pop("active_portfolio_id", None)


def _maybe_autoload_default() -> None:
    """If user has a default vault portfolio and session is demo, load it."""
    user = get_current_user()
    if not user:
        return
    if st.session_state.get("portfolio_source") == "mfcentral_cas":
        return  # don't clobber a fresh CAS import
    if st.session_state.get("portfolio_source") == "vault":
        return
    try:
        default = get_vault().get_default_portfolio(user["id"])
        if default and default.get("holdings"):
            load_portfolio_into_session(default["id"])
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Portfolio session + vault
# ---------------------------------------------------------------------------

def get_active_portfolio_id() -> Optional[int]:
    return st.session_state.get("active_portfolio_id")


def set_active_portfolio_id(portfolio_id: Optional[int]) -> None:
    st.session_state["active_portfolio_id"] = portfolio_id


def init_portfolio_holdings() -> list[dict[str, Any]]:
    if "portfolio_holdings" not in st.session_state:
        # Prefer vault default when logged in
        if is_logged_in():
            try:
                user = get_current_user()
                assert user
                default = get_vault().get_default_portfolio(user["id"])
                if default and default.get("holdings"):
                    rows = get_vault().holdings_for_analyzer(default)
                    st.session_state.portfolio_holdings = rows
                    st.session_state.portfolio_source = "vault"
                    st.session_state.active_portfolio_id = default["id"]
                    return rows
            except Exception:
                pass

        svc = get_fund_service()
        holdings: list[dict[str, Any]] = []
        try:
            searches = [
                ("flexi cap", 250000, 10000),
                ("large cap", 200000, 8000),
                ("mid cap", 150000, 7000),
                ("liquid", 100000, 0),
            ]
            for q, inv, sip in searches:
                df = svc.search_funds(q, limit=5, direct_growth_only=True)
                if df.empty:
                    continue
                row = df.iloc[0]
                holdings.append(
                    {
                        "amfi_code": str(row["amfi_code"]),
                        "scheme_name": row["scheme_name"],
                        "invested_amount": inv,
                        "units": 0,
                        "sip_amount": sip,
                    }
                )
        except Exception:
            holdings = []
        if not holdings:
            from services.data.sample_data import default_demo_portfolio

            holdings = default_demo_portfolio()
        st.session_state.portfolio_holdings = holdings
        st.session_state.portfolio_source = "demo"
    return st.session_state.portfolio_holdings


def set_portfolio_holdings(holdings: list[dict[str, Any]]) -> None:
    st.session_state.portfolio_holdings = holdings
    st.session_state.pop("portfolio_analysis_cache", None)
    st.session_state.pop("portfolio_analysis_fp", None)


def load_portfolio_into_session(portfolio_id: int) -> dict[str, Any]:
    user = get_current_user()
    if not user:
        raise AuthError("Not signed in")
    detail = get_vault().get_portfolio(portfolio_id, user["id"])
    rows = get_vault().holdings_for_analyzer(detail)
    set_portfolio_holdings(rows)
    st.session_state.portfolio_source = "vault"
    set_active_portfolio_id(detail["id"])
    st.session_state.vault_save_name = detail.get("name")
    return detail


def save_session_to_vault(
    *,
    name: Optional[str] = None,
    portfolio_id: Optional[int] = None,
    source: str = "manual",
    as_of_date: Optional[str] = None,
    description: Optional[str] = None,
) -> dict[str, Any]:
    user = get_current_user()
    if not user:
        raise AuthError("Sign in to save portfolios")
    holdings = init_portfolio_holdings()
    saved = get_vault().save_session_holdings(
        user["id"],
        holdings,
        name=name,
        portfolio_id=portfolio_id,
        source=source,
        as_of_date=as_of_date,
        description=description,
    )
    set_active_portfolio_id(saved["id"])
    st.session_state.portfolio_source = source
    return saved


# ---------------------------------------------------------------------------
# Analysis cache
# ---------------------------------------------------------------------------

def get_cached_analysis(
    holdings: Optional[list[dict[str, Any]]] = None,
    *,
    mode: str = "auto",
    force: bool = False,
    progress: Optional[Callable[[float, str], None]] = None,
) -> PortfolioAnalysis:
    holdings = holdings if holdings is not None else init_portfolio_holdings()
    if mode == "auto":
        mode = "fast" if len(holdings) > PortfolioAnalyzerService.FAST_THRESHOLD else "full"

    fp = holdings_fingerprint(holdings, mode=mode)
    cache = st.session_state.get("portfolio_analysis_cache")
    cached_fp = st.session_state.get("portfolio_analysis_fp")

    if not force and cache is not None and cached_fp == fp:
        return cache

    analyzer = get_portfolio_analyzer()
    result = analyzer.analyze(holdings, mode=mode, progress=progress)
    st.session_state["portfolio_analysis_cache"] = result
    st.session_state["portfolio_analysis_fp"] = fp
    st.session_state["portfolio_analysis_mode"] = mode
    return result
