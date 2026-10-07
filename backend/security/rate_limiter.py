from fastapi import HTTPException, Request, status
import time
import logging
from redis import Redis
from redis.exceptions import ConnectionError, TimeoutError

from backend.config.settings import settings

logger = logging.getLogger(__name__)

# Attempt to connect to the actual Redis instance
_redis_client = None
try:
    _real_redis = Redis.from_url(settings.REDIS_URL, socket_timeout=1)
    _real_redis.ping()
    _redis_client = _real_redis
    logger.info(f"Connected to Redis at {settings.REDIS_URL} for rate limiting.")
except (ConnectionError, TimeoutError):
    logger.warning("Could not connect to Redis. Falling back to fakeredis for local development.")
    import fakeredis
    _redis_client = fakeredis.FakeRedis()

async def check_rate_limit(request: Request):
    """
    FastAPI dependency to enforce rate limits per IP using a Redis sliding window.
    """
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    
    key = f"rate_limit:{client_ip}"
    
    # 1. Remove timestamps older than 60 seconds
    cutoff = now - 60
    
    pipeline = _redis_client.pipeline()
    pipeline.zremrangebyscore(key, "-inf", cutoff)
    
    # 2. Count requests in the current window
    pipeline.zcard(key)
    
    # 3. Add the current request timestamp
    pipeline.zadd(key, {str(now): now})
    
    # 4. Set an expiry on the key to prevent stale keys from lingering
    pipeline.expire(key, 60)
    
    results = pipeline.execute()
    request_count = results[1]  # The result of zcard
    
    if request_count >= settings.RATE_LIMIT_PER_MINUTE:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Try again later."
        )
        
    return True
