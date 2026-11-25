"""
Rate limiting với Redis sliding window 60 giây (tiêu chí 7).
"""
from collections import defaultdict, deque
import hashlib
import secrets
import time

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60
_local_windows: dict[str, deque] = defaultdict(deque)


def check_rate_limit(key: str) -> None:
    """Giới hạn RATE_LIMIT_PER_MINUTE request / 60s cho mỗi API key, lưu state trong Redis."""
    now = time.time()
    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

    if not settings.redis_url:
        window = _local_windows[key_hash]
        while window and window[0] < now - WINDOW_SECONDS:
            window.popleft()
        if len(window) >= settings.rate_limit_per_minute:
            retry_after = max(1, int(WINDOW_SECONDS - (now - window[0])) + 1)
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Please retry later.",
                headers={"Retry-After": str(retry_after)},
            )
        window.append(now)
        return

    if r is None:
        raise HTTPException(status_code=503, detail="Redis client not initialized")

    redis_key = f"ratelimit:{key_hash}"
    member = f"{now:.6f}:{secrets.token_hex(4)}"

    try:
        with r.pipeline() as pipe:
            pipe.zremrangebyscore(redis_key, 0, now - WINDOW_SECONDS)
            pipe.zcard(redis_key)
            _, current_count = pipe.execute()

        if current_count >= settings.rate_limit_per_minute:
            oldest = r.zrange(redis_key, 0, 0, withscores=True)
            retry_after = (
                max(1, int(WINDOW_SECONDS - (now - oldest[0][1])) + 1)
                if oldest
                else WINDOW_SECONDS
            )
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Please retry later.",
                headers={"Retry-After": str(retry_after)},
            )

        with r.pipeline() as pipe:
            pipe.zadd(redis_key, {member: now})
            pipe.expire(redis_key, WINDOW_SECONDS + 5)
            pipe.execute()
    except HTTPException:
        raise
    except redis.RedisError as exc:
        raise HTTPException(status_code=503, detail="Rate limiter storage unavailable") from exc
