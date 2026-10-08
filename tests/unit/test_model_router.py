import os
from unittest.mock import patch
from backend.config.model_router import get_llm
from backend.config.settings import settings

def test_get_llm_local():
    """Local tier must return ChatOpenAI pointing to LM Studio."""
    llm = get_llm("local", temperature=0.2)
    assert llm.model_name == settings.LM_STUDIO_MODEL
    assert str(llm.openai_api_base).rstrip("/") == settings.LM_STUDIO_BASE_URL.rstrip("/")

def test_get_llm_strong_fallback():
    """Strong tier without API key must fall back to local model."""
    with patch.dict(os.environ, {}, clear=True):
        with patch.object(settings, "STRONG_MODEL_API_KEY", None):
            llm = get_llm("strong", temperature=0.1)
            assert llm.model_name == settings.LM_STUDIO_MODEL

def test_get_llm_strong_configured():
    """Strong tier with API key and custom provider (e.g. InclusionAI / Ling) must configure ChatOpenAI accordingly."""
    with patch.object(settings, "STRONG_MODEL_API_KEY", "test-key-123"):
        with patch.object(settings, "STRONG_MODEL_NAME", "inclusionai/ling-3.1-flash"):
            with patch.object(settings, "STRONG_MODEL_BASE_URL", "https://api.inclusionai.com/v1"):
                llm = get_llm("strong", temperature=0.0)
                assert llm.model_name == "inclusionai/ling-3.1-flash"
                assert str(llm.openai_api_base).rstrip("/") == "https://api.inclusionai.com/v1"
                assert llm.openai_api_key.get_secret_value() == "test-key-123"
