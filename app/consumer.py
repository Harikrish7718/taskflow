"""
Standalone consumer process. This is deliberately NOT part of the FastAPI
app - it runs as its own long-lived process (its own container in
docker-compose), completely decoupled from the request/response cycle.

This is the core idea Kafka exists for: the API publishes "a task was
created" and moves on immediately. This process, independently, on its own
schedule, reacts to that event - here by maintaining live counters in
Redis. In a real system this same pattern would send a welcome email,
update a search index, trigger a notification, feed an analytics
pipeline, etc. - all without the original API request waiting on any of it,
and all addable later without touching the API code at all.

Run with: python -m app.consumer
"""
import json
import logging

from kafka import KafkaConsumer

from app.config import settings
from app import cache

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("taskflow.consumer")


def run():
    consumer = KafkaConsumer(
        settings.kafka_tasks_topic,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id="taskflow-stats-consumer",
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=True,
    )
    logger.info(f"Listening on topic '{settings.kafka_tasks_topic}'...")

    for message in consumer:
        event = message.value
        event_type = event.get("event_type")
        task_status = event.get("status")
        logger.info(f"Received {event_type} for task {event.get('task_id')}")

        if event_type == "task.created":
            cache.redis_client.incr("stats:tasks_created_total")
            if task_status:
                cache.redis_client.incr(f"stats:tasks_by_status:{task_status}")
        elif event_type == "task.deleted":
            cache.redis_client.decr("stats:tasks_created_total")
            if task_status:
                cache.redis_client.decr(f"stats:tasks_by_status:{task_status}")
        elif event_type == "task.updated":
            # Status may have changed - this simple demo doesn't track the
            # previous status, so it just logs. A production version would
            # include old_status in the event payload to adjust both counters.
            logger.info(f"Task {event.get('task_id')} updated")


if __name__ == "__main__":
    run()
