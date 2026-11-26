from celery import Celery
from kombu import Queue

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "ai_recruiter",
    broker=settings.redis_broker_url,
    backend=settings.redis_backend_url,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_default_queue="queue_ingestion",
    task_queues=(
        Queue("queue_ingestion"),
        Queue("queue_evaluation"),
    ),
    task_routes={
        "app.tasks.ingest_repository_task": {"queue": "queue_ingestion"},
        "app.tasks.ingest_application_portfolio_task": {"queue": "queue_ingestion"},
        "app.tasks.ingest_single_portfolio_repo_task": {"queue": "queue_ingestion"},
        "app.tasks.finalize_portfolio_evaluation_task": {"queue": "queue_ingestion"},
        "app.tasks.evaluate_application_task": {"queue": "queue_evaluation"},
    },
)
