import os
from celery import Celery

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

app = Celery(
    "worker_lite",
    broker=REDIS_URL,
    backend=REDIS_URL.replace("/0", "/1"),
    include=["book_id_task", "pricing_task", "measurement_task"],
)
app.conf.task_serializer = "json"
app.conf.result_serializer = "json"
app.conf.accept_content = ["json"]
app.conf.task_acks_late = True
