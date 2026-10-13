"""
Tests for Phase 4 additions:
  - /metrics endpoint is accessible and returns Prometheus text
  - WebSocket /ws connects and receives broadcast messages
"""
import asyncio
import json
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock

# Use the shared test DB setup from the API tests
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


@pytest.fixture(scope="module")
def client():
    """Spin up the FastAPI app with a fresh in-memory test database."""
    os.environ.setdefault("DATABASE_URL", "sqlite:///./test_phase4.db")
    os.environ.setdefault("JWT_SECRET_KEY", "test-secret-phase4")
    os.environ.setdefault("ENCRYPTION_KEY", "R2yIWPvAweDshbj20vqRMx6OQHEhptrQ5zkmx7ZLNVM=")

    from backend.db.models import init_db
    from backend.main import app

    # Clean up stale test DB
    if os.path.exists("test_phase4.db"):
        os.remove("test_phase4.db")
    init_db()

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    if os.path.exists("test_phase4.db"):
        os.remove("test_phase4.db")


class TestPrometheusMetrics:
    def test_metrics_endpoint_reachable(self, client):
        """The /metrics endpoint must return 200 with Prometheus text format."""
        resp = client.get("/metrics")
        assert resp.status_code == 200
        # Content-type should be text/plain with version
        assert "text/plain" in resp.headers.get("content-type", "")

    def test_metrics_contains_fastapi_instrumentation(self, client):
        """Hit /health first then check metrics contains the default counter."""
        client.get("/health")
        resp = client.get("/metrics")
        body = resp.text
        # prometheus-fastapi-instrumentator exposes http_requests_total or similar
        assert "http" in body.lower()

    def test_custom_dc_metrics_present(self, client):
        """Our custom dc_* metrics should be registered (even if at 0)."""
        resp = client.get("/metrics")
        body = resp.text
        assert "dc_reports_submitted_total" in body
        assert "dc_review_queue_size" in body
        assert "dc_pipeline_duration_seconds" in body


class TestWebSocket:
    def test_websocket_connect_and_disconnect(self, client):
        """Client should be able to connect and disconnect cleanly."""
        with client.websocket_connect("/ws") as ws:
            # Connection accepted — we can disconnect immediately
            pass  # __exit__ closes the connection

    def test_websocket_receives_broadcast(self, client):
        """After a broadcast, the connected client should receive the message."""
        from backend.ws.manager import manager

        with client.websocket_connect("/ws") as ws:
            # Broadcast a fake event from outside the WS connection
            asyncio.get_event_loop().run_until_complete(
                manager.broadcast({"event": "NEED_UPDATED", "need_id": "test-123", "status": "completed"})
            )
            data = ws.receive_json()
            assert data["event"] == "NEED_UPDATED"
            assert data["need_id"] == "test-123"
