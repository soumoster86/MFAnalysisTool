"""Alert generation stubs (manager/expense/NAV events)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from database.session import SessionLocal, init_db
from models.alert import Alert
from utils.logging_config import get_logger

logger = get_logger(__name__)


class AlertService:
    """Create, list, and seed demo alerts. Celery-ready hooks."""

    def ensure_db(self) -> None:
        init_db()

    def create_alert(
        self,
        *,
        alert_type: str,
        title: str,
        message: str,
        severity: str = "info",
        amfi_code: Optional[str] = None,
        scheme_name: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> dict[str, Any]:
        self.ensure_db()
        own = db is None
        db = db or SessionLocal()
        try:
            alert = Alert(
                alert_type=alert_type,
                severity=severity,
                title=title,
                message=message,
                amfi_code=amfi_code,
                scheme_name=scheme_name,
            )
            db.add(alert)
            db.commit()
            db.refresh(alert)
            return self._to_dict(alert)
        finally:
            if own:
                db.close()

    def list_alerts(self, unread_only: bool = False, limit: int = 50) -> list[dict[str, Any]]:
        self.ensure_db()
        with SessionLocal() as db:
            q = db.query(Alert).order_by(Alert.created_at.desc())
            if unread_only:
                q = q.filter(Alert.is_read.is_(False))
            rows = q.limit(limit).all()
            return [self._to_dict(a) for a in rows]

    def mark_read(self, alert_id: int) -> bool:
        self.ensure_db()
        with SessionLocal() as db:
            a = db.get(Alert, alert_id)
            if not a:
                return False
            a.is_read = True
            db.commit()
            return True

    def seed_demo_alerts(self) -> int:
        existing = self.list_alerts(limit=1)
        if existing:
            return 0
        demos = [
            ("nav_drop", "warning", "NAV soft patch detected", "Demo: portfolio sleeve down >3% over 5 sessions."),
            ("manager_change", "critical", "Fund manager change (demo)", "Simulated manager exit on Mid Cap sleeve — review thesis."),
            ("expense_ratio", "info", "TER update (demo)", "Expense ratio revised in last AMC circular (demo data)."),
            ("drawdown", "warning", "Drawdown threshold", "Fund breached -15% peak drawdown alert level."),
            ("overlap", "info", "High portfolio overlap", "Holding overlap across equity sleeves exceeded 40%."),
        ]
        for t, sev, title, msg in demos:
            self.create_alert(alert_type=t, severity=sev, title=title, message=msg)
        return len(demos)

    def evaluate_nav_alerts(
        self,
        scheme_name: str,
        amfi_code: str,
        daily_return: float,
        drawdown: float,
    ) -> list[dict[str, Any]]:
        """Rule hooks callable from Celery tasks."""
        created = []
        if daily_return <= -0.03:
            created.append(
                self.create_alert(
                    alert_type="nav_drop",
                    severity="warning",
                    title=f"NAV drop {daily_return:.1%}",
                    message=f"{scheme_name} daily move {daily_return:.2%}.",
                    amfi_code=amfi_code,
                    scheme_name=scheme_name,
                )
            )
        if drawdown <= -0.15:
            created.append(
                self.create_alert(
                    alert_type="drawdown",
                    severity="critical",
                    title=f"Drawdown {drawdown:.1%}",
                    message=f"{scheme_name} peak drawdown at {drawdown:.1%}.",
                    amfi_code=amfi_code,
                    scheme_name=scheme_name,
                )
            )
        return created

    @staticmethod
    def _to_dict(a: Alert) -> dict[str, Any]:
        return {
            "id": a.id,
            "alert_type": a.alert_type,
            "severity": a.severity,
            "title": a.title,
            "message": a.message,
            "amfi_code": a.amfi_code,
            "scheme_name": a.scheme_name,
            "is_read": a.is_read,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
