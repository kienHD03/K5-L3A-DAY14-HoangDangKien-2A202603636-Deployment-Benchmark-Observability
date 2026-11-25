"""
Kết nối Redis dùng chung cho rate limiter và cost guard.
Không ping Redis lúc import để container vẫn khởi động được khi chưa có Redis.
"""
import redis

from app.config import settings

r = None
if settings.redis_url:
    try:
        r = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=1.5,
            socket_timeout=1.5,
        )
    except Exception:
        r = None


def redis_healthy() -> bool:
    """Kiểm tra kết nối Redis cho readiness probe (GET /ready)."""
    if not settings.redis_url:
        # Chế độ chạy nhanh local khi chưa cấu hình REDIS_URL
        return True
    if r is None:
        return False
    try:
        return bool(r.ping())
    except Exception:
        return False
