"""FastAPI dependencies (auth)."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from services.auth.auth_service import AuthError, get_auth_service

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict[str, Any]:
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return get_auth_service().get_user_from_token(creds.credentials)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_optional_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Optional[dict[str, Any]]:
    if creds is None or not creds.credentials:
        return None
    try:
        return get_auth_service().get_user_from_token(creds.credentials)
    except AuthError:
        return None
