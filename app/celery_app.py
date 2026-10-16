from celery import Celery

# Redis URL pointing to the Docker container running on port 6379.
# '/0' and '/1' represent logical database numbers inside Redis to keep queues and results separated.
REDIS_BROKER_URL = "redis://localhost:6379/0"
REDIS_BACKEND_URL = "redis://localhost:6379/1"

celery_app = Celery(
    "recruiter_worker",
    broker=REDIS_BROKER_URL,
    backend=REDIS_BACKEND_URL,
    include=["app.tasks"]    # Tells Celery where to find our background task functions
)

celery_app.conf.update(
    # Serialization security: only accept JSON, never Python 'pickle' objects (which can execute arbitrary code)
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    
    # Reliability: Worker only tells Redis "I finished this task" AFTER the task finishes running.
    # If the worker container crashes mid-clone, Redis hands the task to another worker.
    task_acks_late=True,
    
    # Prevent a single greedy worker from hoarding tasks while it's busy cloning a big repo
    worker_prefetch_multiplier=1,
    
    # Segregated Queue Routing
    task_routes={
        "app.tasks.ingest_repository_task": {"queue": "queue_ingestion"},
        "app.tasks.evaluate_candidate_task": {"queue": "queue_evaluation"},
    }
)