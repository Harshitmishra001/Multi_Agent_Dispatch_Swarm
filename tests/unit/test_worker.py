import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from backend.tasks.worker import run_graph_task, resume_graph_task, WorkerSettings

@pytest.mark.asyncio
async def test_run_graph_task_success():
    """run_graph_task deserializes report, streams graph, and persists state."""
    report_dict = {
        "report_id": "rpt-worker-1",
        "source_channel": "sms",
        "raw_text": "Need shelter in Sector 5",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "reporter_contact": "555-9999",
    }
    
    with patch("backend.tasks.worker.graph.stream") as mock_stream, \
         patch("backend.tasks.worker._persist_graph_state") as mock_persist, \
         patch("backend.tasks.worker._load_resources", return_value=[]), \
         patch("backend.tasks.worker._load_existing_needs", return_value=[]):
        mock_stream.return_value = []
        
        await run_graph_task(None, report_dict)
        
        assert mock_stream.called
        assert mock_persist.called
        # Assert thread_id passed matches report_id
        args, _ = mock_persist.call_args
        assert args[0] == "rpt-worker-1"
        assert args[1] == "rpt-worker-1"

@pytest.mark.asyncio
async def test_resume_graph_task_success():
    """resume_graph_task streams graph with None input and persists thread state."""
    thread_id = "thread-resume-test"
    
    with patch("backend.tasks.worker.graph.stream") as mock_stream, \
         patch("backend.tasks.worker._persist_graph_state") as mock_persist:
        mock_stream.return_value = []
        
        await resume_graph_task(None, thread_id)
        
        assert mock_stream.called
        assert mock_persist.called
        args, _ = mock_persist.call_args
        assert args[0] == thread_id

def test_worker_settings():
    """WorkerSettings correctly exposes task functions and Redis configuration."""
    assert run_graph_task in WorkerSettings.functions
    assert resume_graph_task in WorkerSettings.functions
    assert WorkerSettings.redis_settings is not None
