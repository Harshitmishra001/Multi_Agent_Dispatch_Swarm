"""
WebSocket connection manager.

Manages connected frontend clients and broadcasts JSON events to all of them
(or a subset by topic). When Redis is available the broadcaster also
subscribes to a Redis Pub/Sub channel so events from worker processes reach
every web worker that is running.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from fastapi import WebSocket
from backend.metrics import WEBSOCKET_CONNECTIONS

if TYPE_CHECKING:
    pass

_log = logging.getLogger(__name__)


class ConnectionManager:
    """Keeps track of all live WebSocket connections and fans out messages."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._redis_pub = None  # Optional Redis client for Pub/Sub publishing

    def set_redis(self, redis_client) -> None:
        """Inject an aioredis client so broadcast() can publish to dc:events."""
        self._redis_pub = redis_client

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)
        WEBSOCKET_CONNECTIONS.inc()
        _log.info("WebSocket connected; total=%d", len(self._connections))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(ws)
        WEBSOCKET_CONNECTIONS.dec()
        _log.info("WebSocket disconnected; total=%d", len(self._connections))

    async def broadcast(self, payload: dict) -> None:
        """Send *payload* (JSON-serialisable dict) to every connected client.

        When a Redis client is configured via set_redis(), the payload is also
        published to the ``dc:events`` channel so every web process receives it,
        enabling cross-process fan-out in multi-container Docker deployments.
        """
        message = json.dumps(payload)
        dead: list[WebSocket] = []

        async with self._lock:
            snapshot = list(self._connections)

        for ws in snapshot:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.discard(ws)
            WEBSOCKET_CONNECTIONS.dec(len(dead))

        # Publish to Redis Pub/Sub so other web-process instances also fan out
        if self._redis_pub is not None:
            try:
                await self._redis_pub.publish("dc:events", message)
            except Exception as exc:
                _log.warning("Failed to publish to Redis dc:events: %s", exc)

    async def broadcast_need_update(
        self,
        event: str,
        need_id: str,
        **extra,
    ) -> None:
        """Convenience wrapper: broadcast a typed NEED_* event."""
        await self.broadcast({"event": event, "need_id": need_id, **extra})

    async def broadcast_plan_ready(self, plan_id: str, passed: bool) -> None:
        """Broadcast when a dispatch plan has been evaluated."""
        await self.broadcast({"event": "PLAN_READY", "plan_id": plan_id, "passed": passed})

    # ── Redis Pub/Sub bridge ──────────────────────────────────────────────────

    async def start_redis_listener(self, redis_url: str) -> None:
        """
        Spin up a background task that subscribes to the Redis channel
        ``dc:events`` and rebroadcasts every message to connected WS clients.

        Call this from the FastAPI lifespan after the Redis pool is available.
        """
        asyncio.create_task(self._redis_listener_loop(redis_url))

    async def _redis_listener_loop(self, redis_url: str) -> None:
        try:
            import redis.asyncio as aioredis

            r = aioredis.from_url(redis_url, decode_responses=True)
            pubsub = r.pubsub()
            await pubsub.subscribe("dc:events")
            _log.info("Redis Pub/Sub listener subscribed to dc:events")

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    payload = json.loads(message["data"])
                    await self.broadcast(payload)
                except (json.JSONDecodeError, Exception) as exc:
                    _log.warning("Bad Redis message: %s", exc)
        except Exception as exc:
            _log.warning(
                "Redis Pub/Sub listener failed (%s); WS broadcasts will still work "
                "for single-process deployments.",
                exc,
            )


# Module-level singleton — imported by routes and workers
manager = ConnectionManager()
