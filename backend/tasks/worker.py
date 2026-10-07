import logging
from arq import Worker
from arq.connections import RedisSettings

from backend.config.settings import settings
from backend.schemas.models import RawReport
from backend.db.models import SessionLocal
from backend.graph.build_graph import build_coordinator_graph
from backend.api.routes import _load_resources, _load_existing_needs, _persist_graph_state

_log = logging.getLogger(__name__)

# Re-use the graph instance here in the worker
graph = build_coordinator_graph()

async def run_graph_task(ctx, report_dict: dict):
    """
    ARQ Task to run the LangGraph pipeline for a new report.
    """
    report = RawReport(**report_dict)
    _log.info(f"Worker processing report {report.report_id}")
    
    db = SessionLocal()
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
    except Exception as e:
        _log.error(f"Error in run_graph_task for {report.report_id}: {e}")
        raise
    finally:
        db.close()

async def resume_graph_task(ctx, thread_id: str):
    """
    ARQ Task to resume the LangGraph pipeline after human review.
    """
    _log.info(f"Worker resuming graph for thread {thread_id}")
    db = SessionLocal()
    try:
        config = {"configurable": {"thread_id": thread_id}}
        for _ in graph.stream(None, config, stream_mode="values"):
            pass
        _persist_graph_state(thread_id, thread_id, db)
    except Exception as e:
        _log.error(f"Error in resume_graph_task for {thread_id}: {e}")
        raise
    finally:
        db.close()

class WorkerSettings:
    functions = [run_graph_task, resume_graph_task]
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
