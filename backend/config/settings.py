from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "sqlite:///./disaster_coordinator.db"

    # JWT — default fallback for test/dev environments if unset in .env
    JWT_SECRET_KEY: str = "dev-secret-key-disaster-coordinator-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # LLM (LM Studio or any OpenAI-compatible endpoint)
    LM_STUDIO_BASE_URL: str = "http://localhost:1234/v1"
    LM_STUDIO_API_KEY: str = "lm-studio"
    LM_STUDIO_MODEL: str = "smollm3-3b"

    # CORS — comma-separated origins, e.g. "http://localhost:5173"
    ALLOWED_ORIGINS: str = "http://localhost:5173"

    # Constraints
    RATE_LIMIT_PER_MINUTE: int = 10
    SOLVER_TIMEOUT_SECONDS: int = 5
    MAX_EVALUATION_RETRIES: int = 2

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()

