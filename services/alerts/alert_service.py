"""Alert CRUD, rules, and evaluation orchestration (Slice B)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from database import session as db_session

# NEVER import Alert/AlertRule from models.alert here — that path caused
# Streamlit Cloud circular ImportError: cannot import name 'AlertRule'.
from services.alerts.db_models import ALERT_ORM_VERSION, Alert, AlertRule
from services.alerts.rules import RuleSpec, default_rules, known_alert_types
from utils.logging_config import get_logger

logger = get_logger(__name__)
logger.info("AlertService ORM source=services.alerts.db_models version={}", ALERT_ORM_VERSION)


def _engine_cls():
    from services.alerts.engine import AlertEngine

    return AlertEngine


class AlertService:
    """Create, list, configure rules, and evaluate real portfolio alerts."""

    def ensure_db(self) -> None:
        try:
            db_session.init_db()
        except Exception as exc:
            logger.warning("init_db during alerts ensure: {}", exc)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Best-effort table/column ensure for SQLite and Postgres."""
        from sqlalchemy import text

        try:
            Alert.__table__.create(bind=db_session.engine, checkfirst=True)
            AlertRule.__table__.create(bind=db_session.engine, checkfirst=True)
        except Exception as exc:
            logger.debug("alert create tables: {}", exc)

        url = str(db_session.engine.url)
        if not url.startswith("sqlite"):
            return
        alters = [
            ("alerts", "user_id", "INTEGER"),
            ("alerts", "portfolio_id", "INTEGER"),
            ("alerts", "rule_id", "INTEGER"),
            ("alerts", "metric_value", "FLOAT"),
            ("alerts", "threshold", "FLOAT"),
            ("alerts", "fingerprint", "VARCHAR(256)"),
            ("alerts", "payload", "TEXT"),
        ]
        try:
            with db_session.engine.begin() as conn:
                for table, col, typedef in alters:
                    try:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}"))
                    except Exception:
                        pass
        except Exception as exc:
            logger.debug("Alert schema ensure skipped: {}", exc)

    # ------------------------------------------------------------------ create / list
    def create_alert(
        self,
        *,
        alert_type: str,
        title: str,
        message: str,
        severity: str = "info",
        amfi_code: Optional[str] = None,
        scheme_name: Optional[str] = None,
        user_id: Optional[int] = None,
        portfolio_id: Optional[int] = None,
        rule_id: Optional[int] = None,
        metric_value: Optional[float] = None,
        threshold: Optional[float] = None,
        fingerprint: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
        db: Optional[Session] = None,
        skip_dedupe: bool = False,
    ) -> Optional[dict[str, Any]]:
        self.ensure_db()
        own = db is None
        db = db or db_session.SessionLocal()
        try:
            if fingerprint and not skip_dedupe:
                since = datetime.utcnow() - timedelta(hours=20)
                existing = (
                    db.query(Alert)
                    .filter(Alert.fingerprint == fingerprint, Alert.created_at >= since)
                    .first()
                )
                if existing:
                    return None
            alert = Alert(
                alert_type=alert_type,
                severity=severity,
                title=title,
                message=message,
                amfi_code=amfi_code,
                scheme_name=scheme_name,
                user_id=user_id,
                portfolio_id=portfolio_id,
                rule_id=rule_id,
                metric_value=metric_value,
                threshold=threshold,
                fingerprint=fingerprint,
                payload=json.dumps(payload) if payload else None,
            )
            db.add(alert)
            db.commit()
            db.refresh(alert)
            return self._to_dict(alert)
        finally:
            if own:
                db.close()

    def list_alerts(
        self,
        *,
        unread_only: bool = False,
        limit: int = 50,
        user_id: Optional[int] = None,
        alert_type: Optional[str] = None,
        severity: Optional[str] = None,
        include_system: bool = True,
    ) -> list[dict[str, Any]]:
        self.ensure_db()
        with db_session.SessionLocal() as db:
            q = db.query(Alert).order_by(Alert.created_at.desc())
            if unread_only:
                q = q.filter(Alert.is_read.is_(False))
            if user_id is not None:
                if include_system:
                    from sqlalchemy import or_

                    q = q.filter(or_(Alert.user_id == user_id, Alert.user_id.is_(None)))
                else:
                    q = q.filter(Alert.user_id == user_id)
            if alert_type:
                q = q.filter(Alert.alert_type == alert_type)
            if severity:
                q = q.filter(Alert.severity == severity)
            rows = q.limit(limit).all()
            return [self._to_dict(a) for a in rows]

    def count_unread(self, user_id: Optional[int] = None) -> dict[str, int]:
        self.ensure_db()
        with db_session.SessionLocal() as db:
            q = db.query(Alert).filter(Alert.is_read.is_(False))
            if user_id is not None:
                from sqlalchemy import or_

                q = q.filter(or_(Alert.user_id == user_id, Alert.user_id.is_(None)))
            rows = q.all()
            by_sev = {"critical": 0, "warning": 0, "info": 0, "total": 0}
            for a in rows:
                by_sev["total"] += 1
                sev = (a.severity or "info").lower()
                if sev in by_sev:
                    by_sev[sev] += 1
            return by_sev

    def mark_read(self, alert_id: int, user_id: Optional[int] = None) -> bool:
        self.ensure_db()
        with db_session.SessionLocal() as db:
            a = db.get(Alert, alert_id)
            if not a:
                return False
            if user_id is not None and a.user_id is not None and a.user_id != user_id:
                return False
            a.is_read = True
            db.commit()
            return True

    def mark_all_read(self, user_id: Optional[int] = None) -> int:
        self.ensure_db()
        with db_session.SessionLocal() as db:
            q = db.query(Alert).filter(Alert.is_read.is_(False))
            if user_id is not None:
                from sqlalchemy import or_

                q = q.filter(or_(Alert.user_id == user_id, Alert.user_id.is_(None)))
            n = 0
            for a in q.all():
                a.is_read = True
                n += 1
            db.commit()
            return n

    def delete_alert(self, alert_id: int, user_id: Optional[int] = None) -> bool:
        self.ensure_db()
        with db_session.SessionLocal() as db:
            a = db.get(Alert, alert_id)
            if not a:
                return False
            if user_id is not None and a.user_id is not None and a.user_id != user_id:
                return False
            db.delete(a)
            db.commit()
            return True

    # ------------------------------------------------------------------ rules
    def list_rules(self, user_id: Optional[int] = None) -> list[dict[str, Any]]:
        """User rules if any; else system defaults (not persisted)."""
        self.ensure_db()
        with db_session.SessionLocal() as db:
            q = db.query(AlertRule)
            if user_id is not None:
                q = q.filter(AlertRule.user_id == user_id)
            else:
                q = q.filter(AlertRule.user_id.is_(None))
            rows = q.order_by(AlertRule.id.asc()).all()
            if rows:
                return [self._rule_to_dict(r) for r in rows]
        return [r.to_dict() for r in default_rules()]

    def get_rule_specs(self, user_id: Optional[int] = None) -> list[RuleSpec]:
        self.ensure_db()
        with db_session.SessionLocal() as db:
            q = db.query(AlertRule).filter(AlertRule.enabled.is_(True))
            if user_id is not None:
                from sqlalchemy import or_

                q = q.filter(or_(AlertRule.user_id == user_id, AlertRule.user_id.is_(None)))
            else:
                q = q.filter(AlertRule.user_id.is_(None))
            rows = q.all()
            if rows:
                return [self._row_to_spec(r) for r in rows]
        return default_rules()

    def seed_default_rules(self, user_id: Optional[int] = None) -> int:
        """Persist default rules for a user (or system if user_id is None)."""
        self.ensure_db()
        with db_session.SessionLocal() as db:
            q = db.query(AlertRule)
            if user_id is None:
                q = q.filter(AlertRule.user_id.is_(None))
            else:
                q = q.filter(AlertRule.user_id == user_id)
            if q.count() > 0:
                return 0
            n = 0
            for spec in default_rules():
                db.add(
                    AlertRule(
                        user_id=user_id,
                        name=spec.name,
                        alert_type=spec.alert_type,
                        enabled=spec.enabled,
                        threshold=spec.threshold,
                        lookback_days=spec.lookback_days,
                        severity=spec.severity,
                        scope=spec.scope,
                    )
                )
                n += 1
            db.commit()
            return n

    def upsert_rule(
        self,
        *,
        user_id: Optional[int],
        name: str,
        alert_type: str,
        threshold: float,
        lookback_days: int = 1,
        severity: str = "warning",
        scope: str = "fund",
        enabled: bool = True,
        rule_id: Optional[int] = None,
        amfi_code: Optional[str] = None,
        portfolio_id: Optional[int] = None,
    ) -> dict[str, Any]:
        if alert_type not in known_alert_types():
            raise ValueError(f"Unknown alert_type: {alert_type}")
        self.ensure_db()
        with db_session.SessionLocal() as db:
            if rule_id is not None:
                row = db.get(AlertRule, rule_id)
                if not row:
                    raise ValueError("Rule not found")
                if user_id is not None and row.user_id not in (None, user_id):
                    raise ValueError("Not allowed to edit this rule")
            else:
                row = AlertRule(user_id=user_id)
                db.add(row)
            row.name = (name or alert_type)[:128]
            row.alert_type = alert_type
            row.threshold = float(threshold)
            row.lookback_days = int(lookback_days)
            row.severity = severity
            row.scope = scope
            row.enabled = bool(enabled)
            row.amfi_code = amfi_code
            row.portfolio_id = portfolio_id
            row.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(row)
            return self._rule_to_dict(row)

    def set_rule_enabled(self, rule_id: int, enabled: bool, user_id: Optional[int] = None) -> bool:
        self.ensure_db()
        with db_session.SessionLocal() as db:
            row = db.get(AlertRule, rule_id)
            if not row:
                return False
            if user_id is not None and row.user_id not in (None, user_id):
                return False
            row.enabled = enabled
            row.updated_at = datetime.utcnow()
            db.commit()
            return True

    def delete_rule(self, rule_id: int, user_id: Optional[int] = None) -> bool:
        self.ensure_db()
        with db_session.SessionLocal() as db:
            row = db.get(AlertRule, rule_id)
            if not row:
                return False
            if user_id is not None and row.user_id not in (None, user_id):
                return False
            db.delete(row)
            db.commit()
            return True

    # ------------------------------------------------------------------ evaluate
    def evaluate_portfolio(
        self,
        holdings: list[dict[str, Any]],
        *,
        user_id: Optional[int] = None,
        portfolio_id: Optional[int] = None,
        rules: Optional[list[RuleSpec]] = None,
        max_funds: int = 25,
        include_overlap: bool = True,
        persist: bool = True,
    ) -> dict[str, Any]:
        specs = rules if rules is not None else self.get_rule_specs(user_id)
        engine = _engine_cls()()
        result = engine.evaluate(
            holdings,
            specs,
            portfolio_id=portfolio_id,
            max_funds=max_funds,
            include_overlap=include_overlap,
        )
        created: list[dict[str, Any]] = []
        if persist:
            for f in result.fired:
                row = self._persist_fired(f, user_id=user_id)
                if row:
                    created.append(row)
        else:
            created = [self._fired_to_dict(f) for f in result.fired]

        return {
            "status": "ok",
            "alerts_created": len(created),
            "candidates": len(result.fired),
            "checked_rules": result.checked_rules,
            "checked_funds": result.checked_funds,
            "errors": result.errors[:20],
            "skipped": result.skipped,
            "alerts": created,
            "orm_version": ALERT_ORM_VERSION,
        }

    def evaluate_amfi_codes(
        self,
        amfi_codes: list[str],
        *,
        user_id: Optional[int] = None,
        max_funds: int = 25,
    ) -> dict[str, Any]:
        holdings = [
            {"amfi_code": str(c), "scheme_name": str(c), "invested_amount": 1.0}
            for c in amfi_codes
        ]
        return self.evaluate_portfolio(
            holdings,
            user_id=user_id,
            max_funds=max_funds,
            include_overlap=False,
        )

    def evaluate_user_vault(
        self,
        user_id: int,
        *,
        portfolio_id: Optional[int] = None,
        max_funds: int = 25,
        include_overlap: bool = False,
    ) -> dict[str, Any]:
        from services.portfolio.vault_service import PortfolioVaultService, VaultError

        vault = PortfolioVaultService()
        summaries: list[dict[str, Any]] = []
        total_created = 0
        if portfolio_id is not None:
            try:
                detail = vault.get_portfolio(portfolio_id, user_id)
            except VaultError as exc:
                return {"status": "error", "message": str(exc), "alerts_created": 0}
            holdings = vault.holdings_for_analyzer(detail)
            out = self.evaluate_portfolio(
                holdings,
                user_id=user_id,
                portfolio_id=detail["id"],
                max_funds=max_funds,
                include_overlap=include_overlap,
            )
            total_created += out.get("alerts_created", 0)
            summaries.append({"portfolio_id": detail["id"], "name": detail.get("name"), **out})
        else:
            for p in vault.list_portfolios(user_id):
                try:
                    detail = vault.get_portfolio(p["id"], user_id)
                except VaultError:
                    continue
                holdings = vault.holdings_for_analyzer(detail)
                if not holdings:
                    continue
                out = self.evaluate_portfolio(
                    holdings,
                    user_id=user_id,
                    portfolio_id=detail["id"],
                    max_funds=max_funds,
                    include_overlap=include_overlap,
                )
                total_created += out.get("alerts_created", 0)
                summaries.append(
                    {
                        "portfolio_id": detail["id"],
                        "name": detail.get("name"),
                        "alerts_created": out.get("alerts_created", 0),
                        "checked_funds": out.get("checked_funds", 0),
                    }
                )
        return {
            "status": "ok",
            "alerts_created": total_created,
            "portfolios": summaries,
            "orm_version": ALERT_ORM_VERSION,
        }

    def seed_demo_alerts(self) -> int:
        return 0

    def evaluate_nav_alerts(
        self,
        scheme_name: str,
        amfi_code: str,
        daily_return: float,
        drawdown: float,
    ) -> list[dict[str, Any]]:
        created = []
        if daily_return <= -0.03:
            row = self.create_alert(
                alert_type="nav_drop",
                severity="warning",
                title=f"NAV drop {daily_return:.1%}",
                message=f"{scheme_name} daily move {daily_return:.2%}.",
                amfi_code=amfi_code,
                scheme_name=scheme_name,
                metric_value=daily_return,
                threshold=-0.03,
                fingerprint=f"nav_drop:{amfi_code}:{datetime.utcnow().date().isoformat()}",
            )
            if row:
                created.append(row)
        if drawdown <= -0.15:
            row = self.create_alert(
                alert_type="drawdown",
                severity="critical",
                title=f"Drawdown {drawdown:.1%}",
                message=f"{scheme_name} peak drawdown at {drawdown:.1%}.",
                amfi_code=amfi_code,
                scheme_name=scheme_name,
                metric_value=drawdown,
                threshold=-0.15,
                fingerprint=f"drawdown:{amfi_code}:{datetime.utcnow().date().isoformat()}",
            )
            if row:
                created.append(row)
        return created

    def _persist_fired(self, f, user_id: Optional[int] = None) -> Optional[dict[str, Any]]:
        return self.create_alert(
            alert_type=f.alert_type,
            title=f.title,
            message=f.message,
            severity=f.severity,
            amfi_code=f.amfi_code,
            scheme_name=f.scheme_name,
            user_id=user_id,
            portfolio_id=f.portfolio_id,
            rule_id=f.rule_id,
            metric_value=f.metric_value,
            threshold=f.threshold,
            fingerprint=f.fingerprint,
            payload=f.payload,
        )

    @staticmethod
    def _fired_to_dict(f) -> dict[str, Any]:
        return {
            "alert_type": f.alert_type,
            "severity": f.severity,
            "title": f.title,
            "message": f.message,
            "amfi_code": f.amfi_code,
            "scheme_name": f.scheme_name,
            "metric_value": f.metric_value,
            "threshold": f.threshold,
            "fingerprint": f.fingerprint,
            "payload": f.payload,
            "rule_id": f.rule_id,
            "portfolio_id": f.portfolio_id,
        }

    @staticmethod
    def _to_dict(a) -> dict[str, Any]:
        payload = None
        if a.payload:
            try:
                payload = json.loads(a.payload)
            except Exception:
                payload = a.payload
        return {
            "id": a.id,
            "user_id": a.user_id,
            "portfolio_id": a.portfolio_id,
            "rule_id": a.rule_id,
            "alert_type": a.alert_type,
            "severity": a.severity,
            "title": a.title,
            "message": a.message,
            "amfi_code": a.amfi_code,
            "scheme_name": a.scheme_name,
            "metric_value": a.metric_value,
            "threshold": a.threshold,
            "fingerprint": a.fingerprint,
            "payload": payload,
            "is_read": a.is_read,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }

    @staticmethod
    def _rule_to_dict(r) -> dict[str, Any]:
        from services.alerts.rules import RULE_HELP

        return {
            "id": r.id,
            "user_id": r.user_id,
            "name": r.name,
            "alert_type": r.alert_type,
            "enabled": r.enabled,
            "threshold": r.threshold,
            "lookback_days": r.lookback_days,
            "severity": r.severity,
            "scope": r.scope,
            "amfi_code": r.amfi_code,
            "portfolio_id": r.portfolio_id,
            "help": RULE_HELP.get(r.alert_type, ""),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }

    @staticmethod
    def _row_to_spec(r) -> RuleSpec:
        return RuleSpec(
            id=r.id,
            user_id=r.user_id,
            name=r.name,
            alert_type=r.alert_type,
            threshold=float(r.threshold),
            lookback_days=int(r.lookback_days or 1),
            severity=r.severity or "warning",
            scope=r.scope or "fund",
            enabled=bool(r.enabled),
            amfi_code=r.amfi_code,
            portfolio_id=r.portfolio_id,
        )
