"""
Cloud / Streamlit bootstrap: map st.secrets → environment variables before Settings load.

Streamlit Cloud injects secrets via st.secrets (not .env files).
Call inject_streamlit_secrets() as early as possible in the app entrypoint.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def is_streamlit_cloud() -> bool:
    """Detect Streamlit Community Cloud (and similar hosted runtimes)."""
    if os.getenv("STREAMLIT_RUNTIME_ENVIRONMENT", "").lower() == "cloud":
        return True
    if os.getenv("STREAMLIT_SHARING_MODE"):
        return True
    # Common mount paths on Streamlit Cloud
    if Path("/mount/src").exists():
        return True
    return False


def _set_env(key: str, value: Any) -> None:
    if value is None:
        return
    s = str(value).strip()
    if not s:
        return
    # Do not override explicit env (local .env / shell wins)
    if not os.environ.get(key):
        os.environ[key] = s


def _flatten_secrets(obj: Any, prefix: str = "") -> dict[str, str]:
    """Flatten nested Streamlit secrets dicts into ENV_STYLE keys."""
    out: dict[str, str] = {}
    if obj is None:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = str(k)
            path = f"{prefix}_{key}" if prefix else key
            if isinstance(v, dict):
                out.update(_flatten_secrets(v, path))
            else:
                out[path] = str(v)
    else:
        if prefix:
            out[prefix] = str(obj)
    return out


def inject_streamlit_secrets() -> None:
    """
    Copy Streamlit secrets into os.environ for pydantic-settings.

    Supports both flat keys and nested tables, e.g.:

        SECRET_KEY = "..."
        OPENAI_API_KEY = "..."
        OPENAI_MODEL = "gpt-5.6-sol"

        [openai]
        api_key = "..."
        model = "gpt-5.6-sol"
    """
    try:
        import streamlit as st

        secrets = st.secrets
    except Exception:
        return

    try:
        # Iterate without raising if empty
        raw: dict[str, Any] = {}
        for key in secrets:
            try:
                raw[key] = secrets[key]
            except Exception:
                continue
    except Exception:
        return

    flat = _flatten_secrets(raw)

    # Direct / common aliases → canonical env names used by Settings
    alias_map = {
        "SECRET_KEY": "SECRET_KEY",
        "secret_key": "SECRET_KEY",
        "OPENAI_API_KEY": "OPENAI_API_KEY",
        "openai_api_key": "OPENAI_API_KEY",
        "openai_api_key_api_key": "OPENAI_API_KEY",  # nested openai.api_key
        "OPENAI_BASE_URL": "OPENAI_BASE_URL",
        "openai_base_url": "OPENAI_BASE_URL",
        "openai_base_url_base_url": "OPENAI_BASE_URL",
        "OPENAI_MODEL": "OPENAI_MODEL",
        "openai_model": "OPENAI_MODEL",
        "openai_model_model": "OPENAI_MODEL",
        "OPENAI_TEMPERATURE": "OPENAI_TEMPERATURE",
        "DATABASE_URL": "DATABASE_URL",
        "database_url": "DATABASE_URL",
        "APP_ENV": "APP_ENV",
        "app_env": "APP_ENV",
        "DEBUG": "DEBUG",
        "LOG_LEVEL": "LOG_LEVEL",
    }

    for src, dest in alias_map.items():
        if src in flat:
            _set_env(dest, flat[src])

    # Also set any already-UPPER keys 1:1
    for k, v in flat.items():
        if k.isupper() and k not in os.environ:
            _set_env(k, v)

    if is_streamlit_cloud():
        _set_env("APP_ENV", os.environ.get("APP_ENV") or "production")
        # Prefer /tmp for sqlite if not configured (Cloud FS is ephemeral but writable)
        if not os.environ.get("DATABASE_URL"):
            _set_env("DATABASE_URL", "sqlite:////tmp/mf_analysis.db")
        if not os.environ.get("DATA_CACHE_DIR"):
            _set_env("DATA_CACHE_DIR", "/tmp/mf_cache")
