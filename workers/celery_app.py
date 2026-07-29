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
    )
except Exception as exc:  # pragma: no cover
    logger.warning("Celery not available: {}", exc)


def get_celery():
    return celery_app
