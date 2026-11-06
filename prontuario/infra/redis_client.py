"""Redis: conexão. Todas as respostas já vêm como str (decode_responses)."""
from __future__ import annotations

from functools import lru_cache

import redis

from ..core.config import get_settings


@lru_cache(maxsize=1)
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(
        get_settings().redis_url,
        decode_responses=True,
        socket_timeout=3,
        socket_connect_timeout=3,
        health_check_interval=30,
    )
