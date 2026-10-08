from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import router
from backend.security.auth import auth_router
from backend.db.models import init_db
from backend.config.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init DB, connect to Redis for tasks. Shutdown: close Redis."""
    init_db()
    
    # Initialize ARQ Redis pool
    import logging
    from arq import create_pool
    from arq.connections import RedisSettings
    from redis.exceptions import ConnectionError, TimeoutError
    import redis.asyncio as aioredis
    
    logger = logging.getLogger(__name__)
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    
    try:
        # Test connection first
        _test_conn = await aioredis.from_url(settings.REDIS_URL, socket_timeout=1)
        await _test_conn.ping()
        await _test_conn.aclose()
        app.state.arq_pool = await create_pool(redis_settings)
        logger.info(f"Connected ARQ task pool to {settings.REDIS_URL}")
    except (ConnectionError, TimeoutError):
        logger.warning("Could not connect to Redis for ARQ tasks. Using in-process asyncio fallback.")
        import fakeredis.aioredis
        import asyncio
        import backend.tasks.worker as worker_module
        
        class FakeArqPool:
            def __init__(self):
                self._redis = fakeredis.aioredis.FakeRedis()
                
            async def enqueue_job(self, job_name, *args, **kwargs):
                logger.info(f"Local fallback executing task in-process: {job_name}")
                if job_name == "run_graph_task" and args:
                    asyncio.create_task(worker_module.run_graph_task(None, args[0]))
                elif job_name == "resume_graph_task" and args:
                    asyncio.create_task(worker_module.resume_graph_task(None, args[0]))
                return None
                
            async def close(self):
                await self._redis.aclose()
                
        app.state.arq_pool = FakeArqPool()
        
    yield
    
    # Shutdown
    if getattr(app.state, "arq_pool", None):
        await app.state.arq_pool.close()


app = FastAPI(title="Disaster Resource Coordinator API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.ALLOWED_ORIGINS.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health", tags=["health"])
async def root_health():
    """Un-versioned health check for load balancers."""
    from datetime import datetime, timezone
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

# Auth router provides POST /token
app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
# Main API router
app.include_router(router, prefix="/api/v1")


if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True)

