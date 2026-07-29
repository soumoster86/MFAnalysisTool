"""Central application settings loaded from environment / .env / Streamlit secrets."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root: MFAnalysisTool/
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Inject Streamlit Cloud secrets into env before Settings() reads them
try:
    from config.cloud_bootstrap import inject_streamlit_secrets, is_streamlit_cloud

    inject_streamlit_secrets()
except Exception:
    def is_streamlit_cloud() -> bool:  # type: ignore[misc]
        return False


def _default_database_url() -> str:
    if is_streamlit_cloud() or os.getenv("MF_USE_TMP_DB", "").lower() in ("1", "true", "yes"):
        return "sqlite:////tmp/mf_analysis.db"
    return f"sqlite:///{(PROJECT_ROOT / 'data' / 'mf_analysis.db').as_posix()}"


def _default_cache_dir() -> Path:
    env = os.getenv("DATA_CACHE_DIR")
    if env:
        return Path(env)
    if is_streamlit_cloud() or os.getenv("MF_USE_TMP_DB", "").lower() in ("1", "true", "yes"):
        return Path("/tmp/mf_cache")
    return PROJECT_ROOT / "data" / "cache"


class Settings(BaseSettings):
    """Runtime configuration for MF Analysis Tool."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "MF Analysis Tool"
    app_env: Literal["development", "staging", "production"] = "development"
    debug: bool = True
    secret_key: str = "dev-secret-change-in-production"
    log_level: str = "INFO"

    # Database
    database_url: str = Field(default_factory=_default_database_url)

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    celery_enabled: bool = False

    # OpenAI-compatible
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    # Leave unset/empty for models that only allow default temperature (e.g. gpt-5.6-sol)
    openai_temperature: Optional[float] = None

    # Data
    amfi_nav_url: str = "https://www.amfiindia.com/spages/NAVAll.txt"
    # Historical NAV providers
    mfapi_base_url: str = "https://api.mfapi.in"
    tigzig_nav_url: str = "https://api.tigzig.com/mf/v1/nav"
    # Holdings: Groww public web API (unofficial)
    holdings_provider: str = "groww"
    allow_synthetic_nav_fallback: bool = True
    allow_sample_holdings_fallback: bool = True
    data_cache_dir: Path = Field(default_factory=_default_cache_dir)
    nav_cache_hours: int = 12
    holdings_cache_hours: int = 24
    sample_data_dir: Path = PROJECT_ROOT / "data" / "sample"
    # Persist fetched NAV history into SQLite (can be large)
    persist_nav_to_db: bool = True
    persist_holdings_to_db: bool = True

    # Auth
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # Servers
    streamlit_server_port: int = 8501
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Risk-free rate (annual, India approx T-bill proxy)
    risk_free_rate: float = 0.065

    # Trading days
    trading_days_per_year: int = 252

    @field_validator("data_cache_dir", mode="before")
    @classmethod
    def _parse_cache_dir(cls, v):  # type: ignore[no-untyped-def]
        if v is None or v == "":
            return _default_cache_dir()
        return Path(v)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_cloud(self) -> bool:
        return is_streamlit_cloud() or self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # Ensure writable dirs exist
    try:
        Path(s.data_cache_dir).mkdir(parents=True, exist_ok=True)
        (Path(s.data_cache_dir) / "nav_history").mkdir(parents=True, exist_ok=True)
        (Path(s.data_cache_dir) / "holdings").mkdir(parents=True, exist_ok=True)
        if s.is_sqlite and "///" in s.database_url:
            # sqlite:////tmp/x.db or sqlite:///./data/x.db
            raw = s.database_url.replace("sqlite:///", "", 1)
            if raw.startswith("/") and not raw.startswith("//"):
                Path(raw).parent.mkdir(parents=True, exist_ok=True)
            else:
                p = PROJECT_ROOT / raw.lstrip("./")
                p.parent.mkdir(parents=True, exist_ok=True)
        s.sample_data_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return s


settings = get_settings()
