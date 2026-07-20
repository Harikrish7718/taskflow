"""
This test talks to a REAL Kafka-compatible broker - unlike test_kafka.py,
which mocks the producer for speed. It's automatically skipped unless
TASKFLOW_KAFKA_INTEGRATION=1 is set (CI sets this after starting a real
broker; see .github/workflows/ci.yml). Don't run this locally unless you
have a broker up: `docker compose up -d redpanda`.
"""
import json
import os

import pytest
from kafka import KafkaProducer, KafkaConsumer

from app.config import settings

pytestmark = pytest.mark.skipif(
    os.environ.get("TASKFLOW_KAFKA_INTEGRATION") != "1",
    reason="Set TASKFLOW_KAFKA_INTEGRATION=1 with a real broker running to run this test",
)


def test_publish_and_consume_round_trip():
    topic = "tasks-events-test"

    producer = KafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )
    consumer = KafkaConsumer(
        topic,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        auto_offset_reset="earliest",
        consumer_timeout_ms=10000,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
    )

    message = {"event_type": "task.created", "task_id": 999, "title": "integration test"}
    producer.send(topic, value=message)
    producer.flush()

    received = None
    for record in consumer:
        received = record.value
        break

    assert received is not None
    assert received["event_type"] == "task.created"
    assert received["task_id"] == 999
