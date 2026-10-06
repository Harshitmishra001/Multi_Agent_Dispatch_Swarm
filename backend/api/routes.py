import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.config.settings import settings
from backend.db.models import (
    DBAllocation, DBDispatchPlan, DBPlanAudit, DBReport, DBResource, DBVerifiedNeed,
    SessionLocal,
)
from backend.graph.build_graph import build_coordinator_graph
from backend.schemas.models import (
    NeedType, RawReport, ResourceRecord, UrgencyLevel, VerifiedNeed,
)
from backend.security.auth import get_current_admin, get_current_reviewer, get_db
from backend.security.input_sanitization import sanitize_report_text
from backend.security.rate_limiter import check_rate_limit

router = APIRouter()

# ponytail: module-level singleton — moves to lifespan app.state if hot-reload causes issues
graph = build_coordinator_graph()


# ---------- Helpers ----------
def _load_resources(db: Session) -> List[ResourceRecord]:
    rows = db.query(DBResource).filter(DBResource.status == "available").all()
    return [
        ResourceRecord(
            resource_id=r.resource_id,
            resource_type=NeedType(r.resource_type),
            quantity_available=r.quantity_available,
            location=(r.lat, r.lon),
            status=r.status,
        )
        for r in rows
        if r.lat is not None and r.lon is not None
    ]


def _load_existing_needs(db: Session) -> List[VerifiedNeed]:
    rows = db.query(DBVerifiedNeed).filter(
        DBVerifiedNeed.requires_human_review == False,
        DBVerifiedNeed.duplicate_of == None,
    ).all()
    needs = []
    for n in rows:
        try:
            needs.append(VerifiedNeed(
                need_id=n.need_id,
                source_report_ids=json.loads(n.source_report_ids) if n.source_report_ids else [],
                location_text=n.location_text,
                coordinates=(n.lat, n.lon) if n.lat and n.lon else None,
                need_type=NeedType(n.need_type),
                quantity_estimate=n.quantity_estimate,
                urgency=UrgencyLevel(n.urgency),
                verification_confidence=n.verification_confidence,
                requires_human_review=n.requires_human_review,
                duplicate_of=n.duplicate_of,
            ))
        except Exception:
            pass  # Skip malformed rows — don't crash the whole pipeline
    return needs


def _persist_graph_state(report_id: str, thread_id: str, db: Session):
    """Write VerifiedNeed and DispatchPlan from completed graph state to DB.

    Inventory reservation is performed atomically inside a single commit:
    for each allocation the corresponding DBResource.quantity_available is
    decremented.  If stock is insufficient the allocation is skipped and a
    warning is logged so the planner can be notified on the next cycle.
    """
    import logging
    _log = logging.getLogger(__name__)

    config = {"configurable": {"thread_id": thread_id}}
    state = graph.get_state(config)
    if not state or not state.values:
        return

    vals = state.values

    # Persist VerifiedNeed
    verified = vals.get("verified_need")
    if verified:
        existing = db.query(DBVerifiedNeed).filter(
            DBVerifiedNeed.need_id == verified.need_id
        ).first()
        if not existing:
            db.add(DBVerifiedNeed(
                need_id=verified.need_id,
                source_report_ids=json.dumps(verified.source_report_ids),
                location_text=verified.location_text,
                lat=verified.coordinates[0] if verified.coordinates else None,
                lon=verified.coordinates[1] if verified.coordinates else None,
                need_type=verified.need_type.value,
                quantity_estimate=verified.quantity_estimate,
                urgency=verified.urgency.value,
                verification_confidence=verified.verification_confidence,
                requires_human_review=verified.requires_human_review,
                duplicate_of=verified.duplicate_of,
            ))

    # Persist DispatchPlan + Allocations with atomic inventory reservation
    plan = vals.get("plan")
    evaluation = vals.get("evaluation")
    if plan:
        existing_plan = db.query(DBDispatchPlan).filter(
            DBDispatchPlan.plan_id == plan.plan_id
        ).first()
        if not existing_plan:
            db.add(DBDispatchPlan(
                plan_id=plan.plan_id,
                generated_at=plan.generated_at,
                narrative=plan.narrative,
                coverage_pct=evaluation.coverage_pct if evaluation else None,
                critical_unmet_count=evaluation.critical_unmet_count if evaluation else None,
                fairness_score=evaluation.fairness_score if evaluation else None,
                passed=evaluation.passed if evaluation else False,
                rationale=evaluation.rationale if evaluation else None,
            ))
            for alloc in plan.allocations:
                # Atomically decrement inventory — skip if stock is depleted
                resource_row = (
                    db.query(DBResource)
                    .filter(DBResource.resource_id == alloc.resource_id)
                    .with_for_update()  # row-level lock inside this transaction
                    .first()
                )
                if resource_row is None:
                    _log.warning(
                        "Allocation skipped — resource %s not found in DB",
                        alloc.resource_id,
                    )
                    continue
                if resource_row.quantity_available < alloc.quantity_allocated:
                    _log.warning(
                        "Allocation skipped — insufficient stock for %s "
                        "(requested %d, available %d)",
                        alloc.resource_id,
                        alloc.quantity_allocated,
                        resource_row.quantity_available,
                    )
                    continue
                # Decrement stock and persist the allocation record together
                resource_row.quantity_available -= alloc.quantity_allocated
                db.add(DBAllocation(
                    plan_id=plan.plan_id,
                    need_id=alloc.need_id,
                    resource_id=alloc.resource_id,
                    quantity_allocated=alloc.quantity_allocated,
                    distance_km=alloc.distance_km,
                    allocation_method=alloc.allocation_method,
                ))

    db.commit()


def _run_graph(report: RawReport, db: Session):
    """Called as a BackgroundTask — runs the full pipeline and persists results."""
    config = {"configurable": {"thread_id": report.report_id}}
    state = {
        "raw_report": report,
        "available_resources": _load_resources(db),
        "existing_needs": _load_existing_needs(db),
    }
    for _ in graph.stream(state, config, stream_mode="values"):
        pass

    _persist_graph_state(report.report_id, report.report_id, db)


# ---------- Request bodies ----------
class ReportSubmission(BaseModel):
    source_channel: str
    raw_text: str
    reporter_contact: Optional[str] = None


class ReviewAction(BaseModel):
    action: str  # "approve" or "reject"


# ---------- Routes ----------
@router.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("/reports", dependencies=[Depends(check_rate_limit)])
async def submit_report(
    submission: ReportSubmission,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    sanitized = sanitize_report_text(submission.raw_text)
    if not sanitized:
        raise HTTPException(status_code=400, detail="Invalid report text")

    report = RawReport(
        report_id=f"rpt-{uuid.uuid4().hex[:8]}",
        source_channel=submission.source_channel,
        raw_text=sanitized,
        submitted_at=datetime.now(timezone.utc),
        reporter_contact=submission.reporter_contact,
    )

    # Persist raw report immediately so it survives regardless of pipeline outcome
    db.add(DBReport(
        report_id=report.report_id,
        source_channel=report.source_channel,
        raw_text=report.raw_text,
        submitted_at=report.submitted_at,
        reporter_contact=report.reporter_contact,
    ))
    db.commit()

    # Run pipeline in background — HTTP returns immediately
    background_tasks.add_task(_run_graph, report, db)

    return {"status": "accepted", "report_id": report.report_id}


@router.get("/reports/{report_id}")
async def get_report_status(
    report_id: str,
    current_user: dict = Depends(get_current_reviewer),
):
    config = {"configurable": {"thread_id": report_id}}
    state = graph.get_state(config)
    if not state or not state.values:
        raise HTTPException(status_code=404, detail="Report not found")

    return {
        "report_id": report_id,
        "extracted_need": state.values.get("extracted_need"),
        "verified_need": state.values.get("verified_need"),
        "pending_review": "human_review" in (state.next or []),
    }


@router.get("/needs/pending-review")
async def get_review_queue(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_reviewer),
):
    rows = db.query(DBVerifiedNeed).filter(
        DBVerifiedNeed.requires_human_review == True
    ).offset(offset).limit(limit).all()
    return {"queue": [
        {
            "need_id": r.need_id,
            "location_text": r.location_text,
            "need_type": r.need_type,
            "urgency": r.urgency,
            "verification_confidence": r.verification_confidence,
            "source_report_ids": json.loads(r.source_report_ids) if r.source_report_ids else [],
            "lat": r.lat,
            "lon": r.lon,
            "quantity_estimate": r.quantity_estimate
        }
        for r in rows
    ]}


@router.post("/needs/{need_id}/review")
async def review_need(
    need_id: str,
    body: ReviewAction,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_reviewer),
):
    if body.action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")

    row = db.query(DBVerifiedNeed).filter(DBVerifiedNeed.need_id == need_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Need not found")

    if body.action == "reject":
        # Mark rejected — pipeline will not continue for this need
        db.delete(row)
        db.commit()
        return {"status": "rejected", "need_id": need_id}

    # Approve: clear the review flag in DB
    row.requires_human_review = False
    db.commit()

    # Resume the LangGraph thread — thread_id is the source report_id
    source_ids = json.loads(row.source_report_ids) if row.source_report_ids else []
    thread_id = source_ids[0] if source_ids else need_id

    def _resume(tid: str):
        config = {"configurable": {"thread_id": tid}}
        for _ in graph.stream(None, config, stream_mode="values"):
            pass
        _db = SessionLocal()
        try:
            _persist_graph_state(tid, tid, _db)
        finally:
            _db.close()

    background_tasks.add_task(_resume, thread_id)
    return {"status": "approved_and_resumed", "need_id": need_id, "thread_id": thread_id}


@router.get("/resources")
async def get_resources(
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_reviewer),  # reviewers may view resource depots on the map
):
    rows = db.query(DBResource).offset(offset).limit(limit).all()
    return {"resources": [
        {
            "resource_id": r.resource_id,
            "resource_type": r.resource_type,
            "quantity_available": r.quantity_available,
            "lat": r.lat,
            "lon": r.lon,
            "status": r.status,
        }
        for r in rows
    ]}


@router.post("/resources")
async def add_resource(
    resource: ResourceRecord,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    db.add(DBResource(
        resource_id=resource.resource_id,
        resource_type=resource.resource_type.value,
        quantity_available=resource.quantity_available,
        lat=resource.location[0],
        lon=resource.location[1],
        status=resource.status,
    ))
    db.commit()
    return {"status": "added", "resource_id": resource.resource_id}


@router.get("/plans/{plan_id}")
async def get_plan(
    plan_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_reviewer),
):
    plan = db.query(DBDispatchPlan).filter(DBDispatchPlan.plan_id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    allocs = db.query(DBAllocation).filter(DBAllocation.plan_id == plan_id).all()
    return {
        "plan_id": plan.plan_id,
        "generated_at": plan.generated_at,
        "narrative": plan.narrative,
        "coverage_pct": plan.coverage_pct,
        "critical_unmet_count": plan.critical_unmet_count,
        "fairness_score": plan.fairness_score,
        "passed": plan.passed,
        "rationale": plan.rationale,
        "allocations": [
            {
                "need_id": a.need_id,
                "resource_id": a.resource_id,
                "quantity_allocated": a.quantity_allocated,
                "distance_km": a.distance_km,
                "allocation_method": a.allocation_method,
            }
            for a in allocs
        ],
    }


@router.post("/plans/{plan_id}/override")
async def override_plan(
    plan_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    plan = db.query(DBDispatchPlan).filter(DBDispatchPlan.plan_id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    now = datetime.now(timezone.utc)
    override_note = f"ADMIN OVERRIDE by {current_user['username']} at {now.isoformat()}"

    # Write an immutable audit record before mutating the plan
    db.add(DBPlanAudit(
        plan_id=plan_id,
        overridden_by=current_user["username"],
        overridden_at=now,
        previous_rationale=plan.rationale,
        new_rationale=override_note,
    ))

    plan.passed = True
    plan.rationale = override_note
    db.commit()
    return {"status": "overridden", "plan_id": plan_id}

