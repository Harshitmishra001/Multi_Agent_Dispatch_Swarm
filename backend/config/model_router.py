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
        api_key = settings.STRONG_MODEL_API_KEY or os.environ.get("OPENAI_API_KEY")
        if api_key:
            kwargs = {
                "api_key": api_key,
                "model": settings.STRONG_MODEL_NAME or os.environ.get("STRONG_MODEL_NAME", "gpt-4o"),
                "temperature": temperature,
            }
            base_url = settings.STRONG_MODEL_BASE_URL or os.environ.get("STRONG_MODEL_BASE_URL")
            if base_url:
                kwargs["base_url"] = base_url
                if "openrouter.ai" in base_url:
                    kwargs["default_headers"] = {
                        "HTTP-Referer": "https://github.com/Harshitmishra001/Multi_Agent_Dispatch_Swarm",
                        "X-Title": "Disaster Resource Coordinator",
                    }
            return ChatOpenAI(**kwargs)
            
    # Fallback / Local Tier
    return ChatOpenAI(
        base_url=settings.LM_STUDIO_BASE_URL,
        api_key=settings.LM_STUDIO_API_KEY,  # type: ignore
        model=settings.LM_STUDIO_MODEL,
        temperature=temperature
    )

