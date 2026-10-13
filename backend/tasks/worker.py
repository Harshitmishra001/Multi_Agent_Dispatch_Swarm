import logging
import time
from arq import Worker
from arq.connections import RedisSettings

from backend.config.settings import settings
from backend.schemas.models import RawReport
from backend.db.models import SessionLocal
from backend.graph.build_graph import build_coordinator_graph
from backend.api.routes import _load_resources, _load_existing_needs, _persist_graph_state
from backend.ws.manager import manager as ws_manager
from backend.metrics import (
    REPORTS_PROCESSED,
    PIPELINE_LATENCY,
)

_log = logging.getLogger(__name__)

# Re-use the graph instance here in the worker
graph = build_coordinator_graph()


async def run_graph_task(ctx, report_dict: dict):
    """
    ARQ Task to run the LangGraph pipeline for a new report.
    Broadcasts NEED_UPDATED events to connected WebSocket clients.
    """
    report = RawReport(**report_dict)
    _log.info(f"Worker processing report {report.report_id}")

    await ws_manager.broadcast_need_update(
        "NEED_PROCESSING",
        need_id=report.report_id,
        status="in_progress",
    )

    db = SessionLocal()
    start = time.monotonic()
    try:
        config = {"configurable": {"thread_id": report.report_id}}
        state = {
            "raw_report": report,
            "available_resources": _load_resources(db),
            "existing_needs": _load_existing_needs(db),
        }
        for _ in graph.stream(state, config, stream_mode="values"):
            pass

        _persist_graph_state(report.report_id, report.report_id, db)

        elapsed = time.monotonic() - start
        PIPELINE_LATENCY.observe(elapsed)
        REPORTS_PROCESSED.labels(status="success").inc()

        await ws_manager.broadcast_need_update(
            "NEED_UPDATED",
            need_id=report.report_id,
            status="completed",
        )

    except Exception as e:
        REPORTS_PROCESSED.labels(status="error").inc()
        await ws_manager.broadcast_need_update(
            "NEED_ERROR",
            need_id=report.report_id,
            status="error",
            error=str(e),
        )
        _log.error(f"Error in run_graph_task for {report.report_id}: {e}")
        raise
    finally:
        db.close()


async def resume_graph_task(ctx, thread_id: str):
    """
    ARQ Task to resume the LangGraph pipeline after human review.
    Broadcasts PLAN_READY once a dispatch plan is evaluated.
    """
    _log.info(f"Worker resuming graph for thread {thread_id}")

    await ws_manager.broadcast_need_update(
        "NEED_RESUMING",
        need_id=thread_id,
        status="resuming",
    )

    db = SessionLocal()
    try:
        config = {"configurable": {"thread_id": thread_id}}
        for _ in graph.stream(None, config, stream_mode="values"):
            pass
        _persist_graph_state(thread_id, thread_id, db)

        # Notify frontend that the resumed pipeline is done
        await ws_manager.broadcast_need_update(
            "NEED_UPDATED",
            need_id=thread_id,
            status="completed",
        )

    except Exception as e:
        await ws_manager.broadcast_need_update(
            "NEED_ERROR",
            need_id=thread_id,
            status="error",
            error=str(e),
        )
        _log.error(f"Error in resume_graph_task for {thread_id}: {e}")
        raise
    finally:
        db.close()


class WorkerSettings:
    functions = [run_graph_task, resume_graph_task]
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
