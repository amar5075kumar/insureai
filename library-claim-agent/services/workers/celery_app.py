"""
Celery application — workers run from /app so module paths are flat.
"""
from __future__ import annotations

import os

from celery import Celery

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

app = Celery(
    "library_claim_workers",
    broker=REDIS_URL,
    backend=REDIS_URL.replace("/0", "/1"),
    include=[
        "book_id.worker",
        "pricing.worker",
        "measurement.worker",
    ],
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_routes={
        "book_id.*":     {"queue": "book_id"},
        "pricing.*":     {"queue": "pricing"},
        "measurement.*": {"queue": "measurement"},
    },
    task_max_retries=3,
    task_default_retry_delay=10,
    result_expires=86_400,
)
