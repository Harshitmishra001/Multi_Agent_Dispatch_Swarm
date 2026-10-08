"""FastAPI HTTP integration tests.

These tests use FastAPI's TestClient to exercise actual HTTP endpoints with a
dedicated file-based SQLite test database and mocked LLM calls.  They
deliberately do NOT mock the database or authentication layer so we validate
real behaviour (auth, permissions, DB writes) end-to-end.
"""

import os
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.db.models import Base, DBUser, DBResource, DBDispatchPlan, DBPlanAudit
from backend.security.auth import get_db  # canonical get_db shared by routes + auth middleware
from backend.main import app


# ---------------------------------------------------------------------------
# Test database — file-based SQLite so connection pool stays consistent
# ---------------------------------------------------------------------------

TEST_DB_PATH = "./test_api_integration.db"
TEST_DB_URL = f"sqlite:///{TEST_DB_PATH}"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="module", autouse=True)
def setup_test_db():
    """Create all tables and seed test users once for the whole module."""
    import bcrypt as _bcrypt

    test_engine.dispose()
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except OSError:
            pass

    Base.metadata.create_all(bind=test_engine)

    def _hash(pw: str) -> str:
        return _bcrypt.hashpw(pw.encode(), _bcrypt.gensalt()).decode()

    db = TestSessionLocal()
    try:
        db.add(DBUser(username="alice", hashed_password=_hash("reviewer_pass"), role="reviewer"))
        db.add(DBUser(username="admin", hashed_password=_hash("admin_pass"), role="admin"))
        db.add(DBResource(
            resource_id="res-test-1",
            resource_type="water",
            quantity_available=100,
            lat=28.6139,
            lon=77.2090,
            status="available",
        ))
        db.commit()
    finally:
        db.close()

    yield

    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)


@pytest.fixture(scope="module")
def client():
    """TestClient with the DB dependency overridden to use the test database."""
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def get_token(client: TestClient, username: str, password: str) -> str:
    resp = client.post(
        "/api/v1/auth/token",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, f"Token fetch failed ({resp.status_code}): {resp.text}"
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_ok(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestAuth:
    def test_reviewer_login_success(self, client):
        token = get_token(client, "alice", "reviewer_pass")
        assert len(token) > 10

    def test_admin_login_success(self, client):
        token = get_token(client, "admin", "admin_pass")
        assert len(token) > 10

    def test_invalid_credentials_rejected(self, client):
        resp = client.post(
            "/api/v1/auth/token",
            data={"username": "alice", "password": "wrong"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert resp.status_code == 401


class TestResourceEndpoint:
    def test_reviewer_can_list_resources(self, client):
        """GET /resources must now work for reviewers (fixes the map 403 bug)."""
        token = get_token(client, "alice", "reviewer_pass")
        resp = client.get("/api/v1/resources", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert "resources" in data
        ids = [r["resource_id"] for r in data["resources"]]
        assert "res-test-1" in ids

    def test_unauthenticated_resources_rejected(self, client):
        resp = client.get("/api/v1/resources")
        assert resp.status_code == 401

    def test_admin_can_add_resource(self, client):
        token = get_token(client, "admin", "admin_pass")
        payload = {
            "resource_id": "res-test-new",
            "resource_type": "food",
            "quantity_available": 50,
            "location": [28.7, 77.1],
            "status": "available",
        }
        resp = client.post(
            "/api/v1/resources",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["resource_id"] == "res-test-new"

    def test_reviewer_cannot_add_resource(self, client):
        """POST /resources must remain admin-only."""
        token = get_token(client, "alice", "reviewer_pass")
        payload = {
            "resource_id": "res-should-fail",
            "resource_type": "food",
            "quantity_available": 10,
            "location": [28.0, 77.0],
            "status": "available",
        }
        resp = client.post(
            "/api/v1/resources",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403


class TestReportSubmission:
    def test_report_accepted(self, client):
        """POST /reports is public and should accept a valid report and encrypt PII."""
        with patch("backend.tasks.worker.run_graph_task") as mock_task:
            resp = client.post(
                "/api/v1/reports",
                json={
                    "source_channel": "sms",
                    "raw_text": "We need water urgently at Downtown.",
                    "reporter_contact": "555-1234",
                },
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "accepted"
        report_id = body["report_id"]
        assert report_id.startswith("rpt-")
        
        # Verify it was encrypted in DB
        db = TestSessionLocal()
        try:
            from backend.db.models import DBReport
            db_report = db.query(DBReport).filter(DBReport.report_id == report_id).first()
            assert db_report is not None
            assert db_report.reporter_contact != "555-1234"
            assert db_report.reporter_contact is not None
            
            # Verify it decrypts back correctly
            from backend.security.pii_encryption import decrypt_pii
            assert decrypt_pii(db_report.reporter_contact) == "555-1234"
        finally:
            db.close()

    def test_empty_report_rejected(self, client):
        resp = client.post(
            "/api/v1/reports",
            json={"source_channel": "sms", "raw_text": ""},
        )
        assert resp.status_code == 400


class TestPendingReview:
    def test_reviewer_can_see_queue(self, client):
        token = get_token(client, "alice", "reviewer_pass")
        resp = client.get(
            "/api/v1/needs/pending-review",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert "queue" in resp.json()

    def test_unauthenticated_queue_rejected(self, client):
        resp = client.get("/api/v1/needs/pending-review")
        assert resp.status_code == 401


class TestPlanOverrideAudit:
    def test_override_creates_audit_record(self, client):
        """Admin override must create a DBPlanAudit record and update plan."""
        from datetime import datetime, timezone

        # Seed a plan directly into the test DB
        db = TestSessionLocal()
        plan_id = "plan-audit-test"
        try:
            db.add(DBDispatchPlan(
                plan_id=plan_id,
                generated_at=datetime.now(timezone.utc),
                narrative="Test plan",
                passed=False,
                rationale="Initial rationale",
            ))
            db.commit()
        finally:
            db.close()

        token = get_token(client, "admin", "admin_pass")
        resp = client.post(
            f"/api/v1/plans/{plan_id}/override",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "overridden"

        # Verify audit row was written
        db = TestSessionLocal()
        try:
            audit = db.query(DBPlanAudit).filter(DBPlanAudit.plan_id == plan_id).first()
            assert audit is not None, "DBPlanAudit record was not created"
            assert audit.overridden_by == "admin"
            assert audit.previous_rationale == "Initial rationale"
            assert "ADMIN OVERRIDE" in audit.new_rationale

            # Verify plan itself was updated
            plan = db.query(DBDispatchPlan).filter(DBDispatchPlan.plan_id == plan_id).first()
            assert plan.passed is True
        finally:
            db.close()
