import uuid
from collections.abc import Callable

from app.tasks import evaluate_application_task, ingest_application_portfolio_task


def dispatch_portfolio_ingestion(application_id: uuid.UUID) -> None:
    ingest_application_portfolio_task.delay(str(application_id))


def dispatch_evaluation_job(application_id: uuid.UUID) -> None:
    evaluate_application_task.delay(str(application_id))


def get_ingestion_dispatcher() -> Callable[[uuid.UUID], None]:
    return dispatch_portfolio_ingestion


def get_evaluation_dispatcher() -> Callable[[uuid.UUID], None]:
    return dispatch_evaluation_job
