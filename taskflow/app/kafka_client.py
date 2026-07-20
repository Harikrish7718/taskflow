"""
Thin wrapper around a Kafka producer.

Design mirrors app/cache.py on purpose: the API's job is to serve HTTP
requests correctly and quickly. Publishing an event is a side effect that
downstream systems (the consumer, analytics, notifications...) care about —
it should never be able to fail or slow down the actual API response. So:

- The producer connects lazily (only on first publish, not at import time)
- Publishing is fire-and-forget from the request's point of view
- Any Kafka error is logged and swallowed, never raised to the caller
"""
import json
import logging

from kafka import KafkaProducer
from kafka.errors import KafkaError

from app.config import settings

logger = logging.getLogger("taskflow.kafka")

_producer: KafkaProducer | None = None


def get_producer() -> KafkaProducer | None:
    global _producer
    if _producer is None:
        try:
            _producer = KafkaProducer(
                bootstrap_servers=settings.kafka_bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                request_timeout_ms=3000,
                api_version_auto_timeout_ms=3000,
            )
        except KafkaError as e:
            logger.warning(f"Kafka producer unavailable: {e}")
            return None
    return _producer


def publish_event(topic: str, payload: dict) -> None:
    """Fire-and-forget publish. Never raises - a Kafka outage must not break the API."""
    producer = get_producer()
    if producer is None:
        return
    try:
        producer.send(topic, value=payload)
        producer.flush(timeout=3)
    except KafkaError as e:
        logger.warning(f"Failed to publish event to {topic}: {e}")
