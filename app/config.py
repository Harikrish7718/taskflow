"""
Centralized configuration. All settings come from environment variables
(with sane local defaults) so the exact same code runs in dev, CI, and prod
just by changing environment variables / secrets — never by editing code.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_name: str = "TaskFlow API"
    environment: str = "development"

    # Database
    database_url: str = "postgresql+psycopg://taskflow:taskflow@localhost:5432/taskflow"

    # Redis cache
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = 60

    # Kafka (event streaming)
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_tasks_topic: str = "tasks-events"

    # Auth
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30


settings = Settings()
