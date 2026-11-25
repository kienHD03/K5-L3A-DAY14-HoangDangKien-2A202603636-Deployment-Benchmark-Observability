"""
Cost guard lưu chi phí tích luỹ trong Redis (tiêu chí 8).
"""
from datetime import datetime, timezone

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006
_local_costs: dict[str, float] = {}


def _cost_keys() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return (
        f"cost:daily:{now.strftime('%Y-%m-%d')}",
        f"cost:monthly:{now.strftime('%Y-%m')}",
    )


def check_budget() -> None:
    """Gọi trước khi gọi LLM. Vượt DAILY_BUDGET_USD hoặc MONTHLY_BUDGET_USD → HTTP 402."""
    daily_key, monthly_key = _cost_keys()

    if not settings.redis_url:
        daily_spent = _local_costs.get(daily_key, 0.0)
        monthly_spent = _local_costs.get(monthly_key, 0.0)
    else:
        if r is None:
            raise HTTPException(status_code=503, detail="Redis client not initialized")
        try:
            daily_raw, monthly_raw = r.mget(daily_key, monthly_key)
            daily_spent = float(daily_raw or 0.0)
            monthly_spent = float(monthly_raw or 0.0)
        except redis.RedisError as exc:
            raise HTTPException(status_code=503, detail="Cost tracking storage unavailable") from exc

    if daily_spent >= settings.daily_budget_usd or monthly_spent >= settings.monthly_budget_usd:
        raise HTTPException(
            status_code=402,
            detail="LLM budget exceeded.",
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi sau khi gọi LLM. Cộng chi phí vào Redis và trả về chi phí request (USD)."""
    cost = (
        (max(1, input_tokens) / 1000.0) * PRICE_INPUT_PER_1K
        + (max(1, output_tokens) / 1000.0) * PRICE_OUTPUT_PER_1K
    )
    daily_key, monthly_key = _cost_keys()
    if not settings.redis_url:
        _local_costs[daily_key] = _local_costs.get(daily_key, 0.0) + cost
        _local_costs[monthly_key] = _local_costs.get(monthly_key, 0.0) + cost
    elif r is not None:
        try:
            with r.pipeline() as pipe:
                pipe.incrbyfloat(daily_key, cost)
                pipe.expire(daily_key, 86400 * 2)
                pipe.incrbyfloat(monthly_key, cost)
                pipe.expire(monthly_key, 86400 * 35)
                pipe.execute()
        except redis.RedisError:
            pass
    return round(cost, 8)
