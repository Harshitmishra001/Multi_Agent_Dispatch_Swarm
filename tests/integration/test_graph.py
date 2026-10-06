import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from backend.schemas.models import RawReport, ExtractedNeed, VerifiedNeed, Allocation, DispatchPlan, EvaluationResult, NeedType, UrgencyLevel
from backend.graph.build_graph import build_coordinator_graph

@pytest.fixture
def graph():
    with patch('backend.agents.ingestion_agent.get_llm'), \
         patch('backend.agents.resource_matcher.get_llm'), \
         patch('backend.agents.plan_synthesizer.get_llm'), \
         patch('backend.agents.evaluator_agent.get_llm'):
        return build_coordinator_graph()

def test_graph_human_review_interrupt(graph):
    # Setup initial state with a raw report
    import uuid
    thread_id = f"test_thread_1_{uuid.uuid4().hex[:8]}"
    report = RawReport(
        report_id="rpt-int-1",
        source_channel="sms",
        raw_text="Need help now, location unclear",
        submitted_at=datetime.now(timezone.utc)
    )
    
    # We patch the agents' process methods to force the path we want to test
    with patch('backend.agents.ingestion_agent.IngestionAgent.process') as mock_ingest, \
         patch('backend.agents.verification_agent.VerificationAgent.process') as mock_verify:
         
        mock_ingest.return_value = ExtractedNeed(
            report_id="rpt-int-1",
            location_text="Unknown",
            need_type=NeedType.OTHER,
            stated_urgency=UrgencyLevel.CRITICAL,
            extraction_confidence=0.1
        )
        
        # Verify agent sees low confidence and flags for review
        mock_verify.return_value = VerifiedNeed(
            need_id="need-1",
            source_report_ids=["rpt-int-1"],
            location_text="Unknown",
            need_type=NeedType.OTHER,
            quantity_estimate=1,
            urgency=UrgencyLevel.CRITICAL,
            verification_confidence=0.1,
            requires_human_review=True, # THIS triggers the interrupt
            duplicate_of=None
        )
        
        config = {"configurable": {"thread_id": thread_id}}
        
        # Run graph
        state = {"raw_report": report}
        for event in graph.stream(state, config, stream_mode="values"):
            pass
            
        # Check if it was interrupted
        snapshot = graph.get_state(config)
        assert snapshot.next == ('human_review',)
        
        # Resume the graph
        for event in graph.stream(None, config, stream_mode="values"):
            pass
            
        final_state = graph.get_state(config)
        # Should have completed the whole flow
        assert len(final_state.next) == 0

def test_graph_evaluator_reject_loop(graph):
    import uuid
    thread_id = f"test_thread_2_{uuid.uuid4().hex[:8]}"
    report = RawReport(
        report_id="rpt-int-2",
        source_channel="sms",
        raw_text="Need water",
        submitted_at=datetime.now(timezone.utc)
    )
    
    with patch('backend.agents.ingestion_agent.IngestionAgent.process') as mock_ingest, \
         patch('backend.agents.verification_agent.VerificationAgent.process') as mock_verify, \
         patch('backend.agents.evaluator_agent.EvaluatorAgent.process') as mock_eval:
         
        mock_ingest.return_value = ExtractedNeed(
            report_id="rpt-int-2",
            location_text="Here",
            need_type=NeedType.WATER,
            stated_urgency=UrgencyLevel.HIGH,
            extraction_confidence=0.9
        )
        
        mock_verify.return_value = VerifiedNeed(
            need_id="need-2",
            source_report_ids=["rpt-int-2"],
            location_text="Here",
            need_type=NeedType.WATER,
            quantity_estimate=10,
            urgency=UrgencyLevel.HIGH,
            verification_confidence=0.9,
            requires_human_review=False
        )
        
        # Evaluator fails on first try, passes on second
        mock_eval.side_effect = [
            EvaluationResult(plan_id="p", coverage_pct=50, critical_unmet_count=0, fairness_score=0.2, passed=False, rationale="Fail 1"),
            EvaluationResult(plan_id="p", coverage_pct=100, critical_unmet_count=0, fairness_score=0.9, passed=True, rationale="Pass 2")
        ]
        
        config = {"configurable": {"thread_id": thread_id}}
        state = {"raw_report": report}
        
        # Run graph
        for event in graph.stream(state, config, stream_mode="values"):
            pass
            
        final_state = graph.get_state(config)
        assert final_state.values["revision_count"] == 2
        assert final_state.values["evaluation"].passed is True
