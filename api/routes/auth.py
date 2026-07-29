"""Auth API routes."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from api.deps import get_current_user
from services.auth.auth_service import AuthError, get_auth_service

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=6)
    full_name: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/register")
def register(body: RegisterRequest) -> dict[str, Any]:
    try:
        user = get_auth_service().register(body.email, body.password, body.full_name)
        # auto-login
        token_payload = get_auth_service().authenticate(body.email, body.password)
        return token_payload
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/login")
def login(body: LoginRequest) -> dict[str, Any]:
    try:
        return get_auth_service().authenticate(body.email, body.password)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.get("/me")
def me(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return user
