"""
Thin cache-aside layer around Redis.

Pattern used throughout the app:
  1. Try to read from cache
  2. On miss, read from DB, then populate cache
  3. On writes (create/update/delete), invalidate the relevant cache key

If Redis is unreachable, we fail open (skip caching) rather than break the
app — caching should never be a single point of failure for correctness.
"""
import json
import redis

from app.config import settings

redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)


def cache_get(key: str):
    try:
        raw = redis_client.get(key)
        return json.loads(raw) if raw else None
    except redis.RedisError:
        return None


def cache_set(key: str, value, ttl: int = settings.cache_ttl_seconds):
    try:
        redis_client.set(key, json.dumps(value), ex=ttl)
    except redis.RedisError:
        pass


def cache_delete(key: str):
    try:
        redis_client.delete(key)
    except redis.RedisError:
        pass
