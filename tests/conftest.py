import fakeredis
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.main import app
from app.database import Base, get_db
from app import cache as cache_module

# In-memory SQLite shared across connections within a test - fast, no external deps
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class FakeKafkaProducer:
    """Captures published events in memory instead of hitting a real broker."""
    def __init__(self):
        self.sent: list[tuple[str, dict]] = []

    def publish(self, topic: str, payload: dict):
        self.sent.append((topic, payload))


@pytest.fixture(autouse=True)
def _reset_db(monkeypatch):
    Base.metadata.create_all(bind=engine)
    cache_module.redis_client = fakeredis.FakeRedis(decode_responses=True)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def fake_kafka(monkeypatch):
    """
    Swaps in a fake Kafka producer so tests never need a real broker.
    BackgroundTasks run synchronously within TestClient's request/response
    cycle, so anything published during a request is already captured by
    the time the test's assertions run.
    """
    fake_producer = FakeKafkaProducer()
    monkeypatch.setattr(
        "app.routers.tasks.publish_event",
        lambda topic, payload: fake_producer.publish(topic, payload),
    )
    return fake_producer


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers(client):
    """Signs up + logs in a user, returns Authorization headers ready to use."""
    client.post("/auth/signup", json={"email": "test@example.com", "password": "secret123"})
    resp = client.post(
        "/auth/login",
        data={"username": "test@example.com", "password": "secret123"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
