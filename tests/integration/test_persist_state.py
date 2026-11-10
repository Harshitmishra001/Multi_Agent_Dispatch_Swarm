"""
Integration tests for _persist_graph_state synchronization:
  - Initial insert of VerifiedNeed and DispatchPlan
  - Update of existing VerifiedNeed properties (quantity, urgency, human review flag)
  - Update of existing DispatchPlan evaluation metrics and narrative
"""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db.models import Base, DBVerifiedNeed, DBDispatchPlan, DBResource
from backend.schemas.models import (
    VerifiedNeed,
    DispatchPlan,
    EvaluationResult,
    Allocation,
    NeedType,
    UrgencyLevel,
)
from backend.api.routes import _persist_graph_state


@pytest.fixture
def db_session():
    """Create a fresh in-memory SQLite database session for each test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_persist_graph_state_updates_existing_need(db_session):
    """When a need already exists in DB, _persist_graph_state should update its mutable fields."""
    need_id = "test-sync-need-1"

    # Step 1: Initial insertion with need requiring human review
    initial_need = VerifiedNeed(
        need_id=need_id,
        source_report_ids=["rpt-1"],
        location_text="Sector 4",
        coordinates=[28.6139, 77.2090],
        need_type=NeedType.WATER,
        quantity_estimate=10,
        urgency=UrgencyLevel.MODERATE,
        verification_confidence=0.6,
        requires_human_review=True,
        duplicate_of=None,
    )

    mock_state_1 = MagicMock()
    mock_state_1.values = {"verified_need": initial_need}

    with patch("backend.api.routes.graph.get_state", return_value=mock_state_1):
        _persist_graph_state("rpt-1", "thread-1", db_session)

    saved = db_session.query(DBVerifiedNeed).filter(DBVerifiedNeed.need_id == need_id).first()
    assert saved is not None
    assert saved.quantity_estimate == 10
    assert saved.urgency == "moderate"
    assert saved.requires_human_review is True

    # Step 2: Human reviews and modifies need (escalates urgency, changes quantity, approves)
    revised_need = VerifiedNeed(
        need_id=need_id,
        source_report_ids=["rpt-1", "rpt-2"],
        location_text="Sector 4 North",
        coordinates=[28.6145, 77.2100],
        need_type=NeedType.WATER,
        quantity_estimate=50,
        urgency=UrgencyLevel.CRITICAL,
        verification_confidence=0.95,
        requires_human_review=False,
        duplicate_of=None,
    )

    mock_state_2 = MagicMock()
    mock_state_2.values = {"verified_need": revised_need}

    with patch("backend.api.routes.graph.get_state", return_value=mock_state_2):
        _persist_graph_state("rpt-1", "thread-1", db_session)

    # Step 3: Verify the existing DB row was updated rather than dropped
    updated = db_session.query(DBVerifiedNeed).filter(DBVerifiedNeed.need_id == need_id).first()
    assert updated is not None
    assert updated.quantity_estimate == 50
    assert updated.urgency == "critical"
    assert updated.location_text == "Sector 4 North"
    assert updated.requires_human_review is False
    assert updated.verification_confidence == 0.95
    assert 'rpt-2' in updated.source_report_ids


def test_persist_graph_state_updates_existing_plan_evaluation(db_session):
    """When a plan is re-evaluated, updated metrics and narrative must update DBDispatchPlan."""
    plan_id = "test-sync-plan-1"

    # Seed resource for allocation
    res = DBResource(
        resource_id="res-1",
        resource_type="water",
        quantity_available=100,
        lat=28.6139,
        lon=77.2090,
    )
    db_session.add(res)
    db_session.commit()

    # Step 1: Initial plan fails evaluation
    initial_plan = DispatchPlan(
        plan_id=plan_id,
        generated_at=datetime.now(timezone.utc),
        allocations=[
            Allocation(
                need_id="need-1",
                resource_id="res-1",
                quantity_allocated=10,
                distance_km=2.5,
                allocation_method="ilp",
            )
        ],
        unmet_needs=[],
        narrative="Initial rough plan draft.",
    )
    eval_1 = EvaluationResult(
        plan_id=plan_id,
        coverage_pct=60.0,
        critical_unmet_count=1,
        fairness_score=0.4,
        passed=False,
        rationale="Insufficient critical coverage.",
    )

    mock_state_1 = MagicMock()
    mock_state_1.values = {"plan": initial_plan, "evaluation": eval_1}

    with patch("backend.api.routes.graph.get_state", return_value=mock_state_1):
        _persist_graph_state("rpt-1", "thread-1", db_session)

    saved_plan = db_session.query(DBDispatchPlan).filter(DBDispatchPlan.plan_id == plan_id).first()
    assert saved_plan is not None
    assert saved_plan.passed is False
    assert saved_plan.coverage_pct == 60.0

    # Step 2: Replanning succeeds on second cycle
    revised_plan = DispatchPlan(
        plan_id=plan_id,
        generated_at=datetime.now(timezone.utc),
        allocations=[],  # No new allocations
        unmet_needs=[],
        narrative="Revised and verified dispatch plan.",
    )
    eval_2 = EvaluationResult(
        plan_id=plan_id,
        coverage_pct=100.0,
        critical_unmet_count=0,
        fairness_score=0.9,
        passed=True,
        rationale="All critical needs covered fairly.",
    )

    mock_state_2 = MagicMock()
    mock_state_2.values = {"plan": revised_plan, "evaluation": eval_2}

    with patch("backend.api.routes.graph.get_state", return_value=mock_state_2):
        _persist_graph_state("rpt-1", "thread-1", db_session)

    # Step 3: Verify the existing DB plan row has updated metrics and passed=True
    updated_plan = db_session.query(DBDispatchPlan).filter(DBDispatchPlan.plan_id == plan_id).first()
    assert updated_plan is not None
    assert updated_plan.passed is True
    assert updated_plan.coverage_pct == 100.0
    assert updated_plan.critical_unmet_count == 0
    assert updated_plan.fairness_score == 0.9
    assert updated_plan.narrative == "Revised and verified dispatch plan."
