import os
from langchain_openai import ChatOpenAI
from typing import Literal
from backend.config.settings import settings

ModelTier = Literal["local", "strong"]

def get_llm(tier: ModelTier, temperature: float = 0.0) -> ChatOpenAI:
    """
    Model selection factory that resolves the LLM by tier.
    - 'local': Uses the local LM Studio instance (e.g., smollm3-3b).
    - 'strong': Uses a cloud provider (e.g., OpenAI gpt-4o) if an API key is set,
      otherwise falls back to the local model.
    """
    if tier == "strong":
        # Check if an OpenAI API key is provided via environment
        openai_key = os.environ.get("OPENAI_API_KEY")
        if openai_key:
            return ChatOpenAI(
                api_key=openai_key, # type: ignore
                model="gpt-4o",
                temperature=temperature
            )
            
    # Fallback / Local Tier
    return ChatOpenAI(
        base_url=settings.LM_STUDIO_BASE_URL,
        api_key=settings.LM_STUDIO_API_KEY,  # type: ignore
        model=settings.LM_STUDIO_MODEL,
        temperature=temperature
    )

