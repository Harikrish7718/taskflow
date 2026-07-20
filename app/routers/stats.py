from fastapi import APIRouter

from app import cache
from app.models import TaskStatus

router = APIRouter(tags=["stats"])


@router.get("/stats")
def get_stats():
    """
    Reads counters maintained by the Kafka consumer (app/consumer.py), not
    computed from the database. This endpoint proves the event pipeline is
    actually working end to end: API -> Kafka -> consumer -> Redis -> here.
    If these numbers are stale, the consumer isn't running or isn't caught up.
    """
    total = cache.redis_client.get("stats:tasks_created_total") or 0
    by_status = {
        s.value: int(cache.redis_client.get(f"stats:tasks_by_status:{s.value}") or 0)
        for s in TaskStatus
    }
    return {
        "tasks_created_total": int(total),
        "tasks_by_status": by_status,
        "source": "kafka-consumer-derived (eventually consistent)",
    }
