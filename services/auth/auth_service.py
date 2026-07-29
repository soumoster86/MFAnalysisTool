"""User registration, login, and JWT helpers."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from jose import JWTError, jwt
from sqlalchemy.orm import Session

from config.settings import settings
from database import session as db_session
from models.user import User
from utils.logging_config import get_logger

logger = get_logger(__name__)

ALGORITHM = settings.jwt_algorithm
# Prefer SECRET_KEY; fall back for older .env
SECRET = settings.secret_key
EXPIRE_MINUTES = settings.jwt_expire_minutes


class AuthError(Exception):
    """Raised for authentication / authorization failures."""


def hash_password(password: str) -> str:
    """PBKDF2-SHA256 hash (stdlib — no bcrypt platform issues)."""
    if not password or len(password) < 6:
        raise AuthError("Password must be at least 6 characters")
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return f"pbkdf2_sha256${salt}${dk.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    try:
        algo, salt, digest = hashed.split("$", 2)
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000
        )
        return secrets.compare_digest(dk.hex(), digest)
    except Exception:
        return False


def create_access_token(
    subject: str,
    *,
    extra: Optional[dict[str, Any]] = None,
    expires_minutes: Optional[int] = None,
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes if expires_minutes is not None else EXPIRE_MINUTES
    )
    payload: dict[str, Any] = {"sub": subject, "exp": expire}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, SECRET, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise AuthError("Invalid or expired token") from exc


class AuthService:
    """User account operations."""

    def ensure_db(self) -> None:
        db_session.init_db()

    def register(
        self,
        email: str,
        password: str,
        full_name: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> dict[str, Any]:
        self.ensure_db()
        email = (email or "").strip().lower()
        if not email or "@" not in email:
            raise AuthError("Valid email is required")
        own = db is None
        db = db or db_session.SessionLocal()
        try:
            existing = db.query(User).filter(User.email == email).one_or_none()
            if existing:
                raise AuthError("Email already registered")
            user = User(
                email=email,
                hashed_password=hash_password(password),
                full_name=(full_name or "").strip() or None,
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            logger.info("Registered user {}", email)
            return self._user_dict(user)
        finally:
            if own:
                db.close()

    def authenticate(
        self, email: str, password: str, db: Optional[Session] = None
    ) -> dict[str, Any]:
        self.ensure_db()
        email = (email or "").strip().lower()
        own = db is None
        db = db or db_session.SessionLocal()
        try:
            user = db.query(User).filter(User.email == email).one_or_none()
            if not user or not verify_password(password, user.hashed_password):
                raise AuthError("Invalid email or password")
            if not user.is_active:
                raise AuthError("Account is disabled")
            token = create_access_token(
                str(user.id),
                extra={"email": user.email, "name": user.full_name or ""},
            )
            return {
                "access_token": token,
                "token_type": "bearer",
                "user": self._user_dict(user),
            }
        finally:
            if own:
                db.close()

    def get_user_by_id(self, user_id: int, db: Optional[Session] = None) -> Optional[dict[str, Any]]:
        self.ensure_db()
        own = db is None
        db = db or db_session.SessionLocal()
        try:
            user = db.get(User, user_id)
            if not user or not user.is_active:
                return None
            return self._user_dict(user)
        finally:
            if own:
                db.close()

    def get_user_from_token(self, token: str, db: Optional[Session] = None) -> dict[str, Any]:
        payload = decode_access_token(token)
        sub = payload.get("sub")
        if not sub:
            raise AuthError("Invalid token payload")
        user = self.get_user_by_id(int(sub), db=db)
        if not user:
            raise AuthError("User not found or inactive")
        return user

    @staticmethod
    def _user_dict(user: User) -> dict[str, Any]:
        return {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }


_auth: Optional[AuthService] = None


def get_auth_service() -> AuthService:
    global _auth
    if _auth is None:
        _auth = AuthService()
    return _auth
