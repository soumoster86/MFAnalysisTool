"""Sample holdings and demo portfolio generators (holdings not on AMFI feed)."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

# Representative India equity universe for synthetic holdings
UNIVERSE = [
    ("Reliance Industries", "Energy", "Large"),
    ("HDFC Bank", "Financials", "Large"),
    ("ICICI Bank", "Financials", "Large"),
    ("Infosys", "IT", "Large"),
    ("TCS", "IT", "Large"),
    ("Bharti Airtel", "Telecom", "Large"),
    ("ITC", "FMCG", "Large"),
    ("Larsen & Toubro", "Industrials", "Large"),
    ("Axis Bank", "Financials", "Large"),
    ("State Bank of India", "Financials", "Large"),
    ("Bajaj Finance", "Financials", "Large"),
    ("Kotak Mahindra Bank", "Financials", "Large"),
    ("Hindustan Unilever", "FMCG", "Large"),
    ("Asian Paints", "Materials", "Large"),
    ("Maruti Suzuki", "Auto", "Large"),
    ("Sun Pharma", "Healthcare", "Large"),
    ("Titan Company", "Consumer", "Large"),
    ("UltraTech Cement", "Materials", "Large"),
    ("Nestle India", "FMCG", "Large"),
    ("Power Grid", "Utilities", "Large"),
    ("NTPC", "Utilities", "Large"),
    ("Tata Motors", "Auto", "Large"),
    ("Tech Mahindra", "IT", "Large"),
    ("Wipro", "IT", "Large"),
    ("HCL Technologies", "IT", "Large"),
    ("Avenue Supermarts", "Consumer", "Large"),
    ("Adani Enterprises", "Industrials", "Large"),
    ("Adani Ports", "Industrials", "Large"),
    ("JSW Steel", "Materials", "Large"),
    ("Tata Steel", "Materials", "Large"),
    ("IndusInd Bank", "Financials", "Large"),
    ("Bajaj Finserv", "Financials", "Large"),
    ("Cipla", "Healthcare", "Large"),
    ("Dr Reddy's", "Healthcare", "Large"),
    ("Eicher Motors", "Auto", "Large"),
    ("Hero MotoCorp", "Auto", "Large"),
    ("BPCL", "Energy", "Large"),
    ("ONGC", "Energy", "Large"),
    ("Coal India", "Energy", "Large"),
    ("Grasim Industries", "Materials", "Large"),
    ("Persistent Systems", "IT", "Mid"),
    ("Coforge", "IT", "Mid"),
    ("PI Industries", "Materials", "Mid"),
    ("Dixon Technologies", "Consumer", "Mid"),
    ("Federal Bank", "Financials", "Mid"),
    ("AU Small Finance", "Financials", "Mid"),
    ("Max Healthcare", "Healthcare", "Mid"),
    ("Polycab", "Industrials", "Mid"),
    ("Astral", "Industrials", "Mid"),
    ("Page Industries", "Consumer", "Mid"),
    ("Cummins India", "Industrials", "Mid"),
    ("Supreme Industries", "Materials", "Mid"),
    ("Indian Hotels", "Consumer", "Mid"),
    ("Yes Bank", "Financials", "Mid"),
    ("Voltas", "Consumer", "Mid"),
    ("Trent", "Consumer", "Large"),
    ("Zomato", "Consumer", "Large"),
    ("PB Fintech", "Financials", "Mid"),
    ("Kaynes Technology", "Industrials", "Small"),
    ("Mazagon Dock", "Industrials", "Mid"),
    ("Suzlon Energy", "Energy", "Mid"),
    ("IRCTC", "Consumer", "Mid"),
    ("KPIT Technologies", "IT", "Mid"),
    ("Apar Industries", "Industrials", "Small"),
    ("Cera Sanitaryware", "Consumer", "Small"),
    ("Laurus Labs", "Healthcare", "Mid"),
    ("Glenmark Pharma", "Healthcare", "Mid"),
    ("Jubilant Foodworks", "Consumer", "Mid"),
    ("Deepak Nitrite", "Materials", "Mid"),
    ("Aarti Industries", "Materials", "Mid"),
]


def ensure_sample_holdings(
    amfi_code: str,
    scheme_name: str,
    category: str = "Flexi Cap",
    n: int = 35,
) -> pd.DataFrame:
    """Deterministic pseudo-holdings based on scheme code and category."""
    seed = int(amfi_code) if str(amfi_code).isdigit() else abs(hash(amfi_code)) % (10**8)
    rng = np.random.default_rng(seed)

    cat = category.lower()
    if "small" in cat:
        pool = [u for u in UNIVERSE if u[2] in ("Small", "Mid")] or UNIVERSE
        n = min(n, 40)
    elif "mid" in cat:
        pool = [u for u in UNIVERSE if u[2] in ("Mid", "Large")]
        n = min(n, 40)
    elif "large" in cat:
        pool = [u for u in UNIVERSE if u[2] == "Large"]
        n = min(n, 30)
    elif "debt" in cat or "liquid" in cat or "gilt" in cat:
        # Debt-like: cash + bonds proxy
        rows = [
            {"security_name": "Treasury Bills", "sector": "Sovereign", "market_cap": "N/A", "weight_pct": 35.0, "country": "India", "asset_type": "Debt"},
            {"security_name": "AAA Corporate Bonds", "sector": "Financials", "market_cap": "N/A", "weight_pct": 30.0, "country": "India", "asset_type": "Debt"},
            {"security_name": "Certificate of Deposit", "sector": "Financials", "market_cap": "N/A", "weight_pct": 20.0, "country": "India", "asset_type": "Debt"},
            {"security_name": "Cash & Equivalents", "sector": "Cash", "market_cap": "N/A", "weight_pct": 15.0, "country": "India", "asset_type": "Cash"},
        ]
        return pd.DataFrame(rows)
    else:
        pool = UNIVERSE
        n = min(n, 45)

    idx = rng.choice(len(pool), size=min(n, len(pool)), replace=False)
    picks = [pool[i] for i in idx]
    # Dirichlet-like weights
    raw = rng.exponential(1.0, size=len(picks))
    # Boost first few for realistic concentration
    raw = np.sort(raw)[::-1]
    raw = raw / raw.sum() * 92.0  # leave ~8% cash/others
    rows = []
    for (name, sector, mcap), w in zip(picks, raw):
        rows.append(
            {
                "security_name": name,
                "sector": sector,
                "market_cap": mcap,
                "weight_pct": round(float(w), 2),
                "country": "India",
                "asset_type": "Equity",
            }
        )
    rows.append(
        {
            "security_name": "Cash & Others",
            "sector": "Cash",
            "market_cap": "N/A",
            "weight_pct": round(100.0 - sum(r["weight_pct"] for r in rows), 2),
            "country": "India",
            "asset_type": "Cash",
        }
    )
    return pd.DataFrame(rows)


def generate_sample_portfolio_funds() -> pd.DataFrame:
    """Offline fallback scheme list if AMFI is unreachable."""
    data = [
        {"amfi_code": "120503", "scheme_name": "Demo Flexi Cap Fund - Direct Growth", "amc": "Demo AMC", "category": "Equity", "subcategory": "Flexi Cap", "nav": 85.4, "nav_date": pd.Timestamp.today().normalize()},
        {"amfi_code": "120716", "scheme_name": "Demo Large Cap Fund - Direct Growth", "amc": "Demo AMC", "category": "Equity", "subcategory": "Large Cap", "nav": 62.1, "nav_date": pd.Timestamp.today().normalize()},
        {"amfi_code": "125497", "scheme_name": "Demo Mid Cap Fund - Direct Growth", "amc": "Demo AMC", "category": "Equity", "subcategory": "Mid Cap", "nav": 112.3, "nav_date": pd.Timestamp.today().normalize()},
        {"amfi_code": "119551", "scheme_name": "Demo Small Cap Fund - Direct Growth", "amc": "Demo AMC", "category": "Equity", "subcategory": "Small Cap", "nav": 145.0, "nav_date": pd.Timestamp.today().normalize()},
        {"amfi_code": "118989", "scheme_name": "Demo ELSS Fund - Direct Growth", "amc": "Demo AMC", "category": "Equity", "subcategory": "ELSS", "nav": 78.9, "nav_date": pd.Timestamp.today().normalize()},
        {"amfi_code": "119598", "scheme_name": "Demo Liquid Fund - Direct Growth", "amc": "Demo AMC", "category": "Debt", "subcategory": "Liquid", "nav": 3500.0, "nav_date": pd.Timestamp.today().normalize()},
        {"amfi_code": "120465", "scheme_name": "Demo Aggressive Hybrid - Direct Growth", "amc": "Demo AMC", "category": "Hybrid", "subcategory": "Hybrid", "nav": 48.2, "nav_date": pd.Timestamp.today().normalize()},
    ]
    df = pd.DataFrame(data)
    df["is_direct"] = True
    df["is_growth"] = True
    return df


def default_demo_portfolio() -> list[dict]:
    """Default holdings for Dashboard / Portfolio Analyzer demos."""
    return [
        {
            "amfi_code": "120503",
            "scheme_name": "Flexi Cap Sleeve (resolve via search)",
            "invested_amount": 250000,
            "units": 0,
            "sip_amount": 10000,
        },
        {
            "amfi_code": "120716",
            "scheme_name": "Large Cap Sleeve",
            "invested_amount": 200000,
            "units": 0,
            "sip_amount": 8000,
        },
        {
            "amfi_code": "125497",
            "scheme_name": "Mid Cap Sleeve",
            "invested_amount": 150000,
            "units": 0,
            "sip_amount": 7000,
        },
        {
            "amfi_code": "119598",
            "scheme_name": "Liquid Sleeve",
            "invested_amount": 100000,
            "units": 0,
            "sip_amount": 0,
        },
    ]
