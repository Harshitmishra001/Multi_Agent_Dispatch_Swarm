import pytest
import numpy as np
from unittest.mock import patch, MagicMock

from backend.schemas.models import ExtractedNeed, VerifiedNeed, NeedType, UrgencyLevel
from backend.agents.verification_agent import VerificationAgent

@pytest.fixture
def agent():
    agent = VerificationAgent()
    
    # Mock the embedding model to return predictable vectors
    class MockModel:
        def encode(self, texts):
            import numpy as np
            vecs = []
            for t in texts:
                vec = np.zeros(384)
                if 'Main St' in t:
                    vec[0] = 1.0
                else:
                    vec[1] = 1.0
                vecs.append(vec)
            return vecs
            
    agent.model = MockModel()
    return agent

def test_verification_agent_low_confidence(agent):
    extracted = ExtractedNeed(
        report_id="rpt-1",
        location_text="Unknown",
        need_type=NeedType.MEDICAL,
        quantity_estimate=5,
        stated_urgency=UrgencyLevel.CRITICAL,
        extraction_confidence=0.1 # Low!
    )
    
    result = agent.process(extracted, [])
    assert result.requires_human_review is True
    assert result.duplicate_of is None

def test_verification_agent_dedup(agent):
    extracted = ExtractedNeed(
        report_id="rpt-2",
        location_text="Main St Shelter",
        need_type=NeedType.MEDICAL,
        quantity_estimate=2,
        stated_urgency=UrgencyLevel.HIGH,
        extraction_confidence=0.9
    )
    
    existing = VerifiedNeed(
        need_id="need-existing",
        source_report_ids=["rpt-old"],
        location_text="Main St",
        need_type=NeedType.MEDICAL,
        quantity_estimate=5,
        urgency=UrgencyLevel.CRITICAL,
        verification_confidence=0.9,
        requires_human_review=False
    )
    
    agent._get_vdb().upsert_need(existing, agent.model.encode([f"{existing.location_text} {existing.need_type.value}"])[0])
    
    result = agent.process(extracted, [existing])
    assert result.requires_human_review is False
    assert result.duplicate_of == "need-existing"
    assert "rpt-2" in result.source_report_ids
    assert "rpt-old" in result.source_report_ids

def test_verification_agent_fallback_mode():
    agent = VerificationAgent(similarity_threshold=0.8)
    agent._is_fallback = True
    agent.model = None

    extracted = ExtractedNeed(
        report_id="rpt-fallback",
        location_text="123 Main Street",
        need_type=NeedType.WATER,
        quantity_estimate=10,
        stated_urgency=UrgencyLevel.HIGH,
        extraction_confidence=0.9
    )

    existing = VerifiedNeed(
        need_id="need-fallback-old",
        source_report_ids=["rpt-old-1"],
        location_text="123 Main Street",
        need_type=NeedType.WATER,
        quantity_estimate=5,
        urgency=UrgencyLevel.HIGH,
        verification_confidence=0.9,
        requires_human_review=False
    )

    result = agent.process(extracted, [existing])
    assert result.duplicate_of == "need-fallback-old"
    assert "rpt-fallback" in result.source_report_ids
