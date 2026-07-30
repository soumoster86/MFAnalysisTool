"""Celery application (optional — enable with CELERY_ENABLED=true + Redis)."""

from __future__ import annotations

from config.settings import settings
from utils.logging_config import get_logger

logger = get_logger(__name__)

celery_app = None

try:
    from celery import Celery

    celery_app = Celery(
        "mf_analysis",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=["workers.tasks"],
    )
    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="Asia/Kolkata",
        enable_utc=True,
        task_track_started=True,
        task_always_eager=not settings.celery_enabled,  # run inline if disabled
        # Slice B — periodic alert evaluation + AMFI refresh (requires celery beat)
        beat_schedule={
            "evaluate-vault-alerts-hourly": {
                "task": "workers.tasks.evaluate_all_vault_alerts",
                "schedule": 3600.0,  # seconds
                "kwargs": {"max_users": 50, "max_funds": 15},
            },
            "refresh-amfi-daily": {
                "task": "workers.tasks.refresh_amfi",
                "schedule": 86400.0,
                "kwargs": {"force": True},
            },
            # Fund attributes move on the order of weeks, and each run costs a
            # meta + holdings fetch per fund — daily is plenty.
            "detect-fund-changes-daily": {
                "task": "workers.tasks.detect_all_vault_changes",
                "schedule": 86400.0,
                "kwargs": {"max_users": 50, "max_funds": 15},
            },
            # Screener scores: batches through the universe, re-scoring what it
            # already has so rankings track the latest NAV.
            "score-fund-universe-nightly": {
                "task": "workers.tasks.score_fund_universe",
                "schedule": 86400.0,
                "kwargs": {"limit": 500, "rescore": True},
            },
        },
    )
except Exception as exc:  # pragma: no cover
    logger.warning("Celery not available: {}", exc)


def get_celery():
    return celery_app
