from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "sqlite:///./disaster_coordinator.db"

    # JWT: default fallback for test/dev environments if unset in .env
    JWT_SECRET_KEY: str = "dev-secret-key-disaster-coordinator-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Encryption key for PII at rest (must be 32 URL-safe base64-encoded bytes)
    ENCRYPTION_KEY: str = "R2yIWPvAweDshbj20vqRMx6OQHEhptrQ5zkmx7ZLNVM="

    # Redis (for distributed rate limiting and Celery/ARQ tasks)
    REDIS_URL: str = "redis://localhost:6379/0"


    # LLM: Local Tier (LM Studio or local OpenAI-compatible endpoint)
    LM_STUDIO_BASE_URL: str = "http://localhost:1234/v1"
    LM_STUDIO_API_KEY: str = "lm-studio"
    LM_STUDIO_MODEL: str = "smollm3-3b"

    # LLM: Strong Tier (OpenAI, OpenRouter, InclusionAI / Ling, etc.)
    STRONG_MODEL_BASE_URL: Optional[str] = None
    STRONG_MODEL_API_KEY: Optional[str] = None
    STRONG_MODEL_NAME: str = "gpt-4o"

    # CORS: comma-separated origins, e.g. "http://localhost:5173"
    ALLOWED_ORIGINS: str = "http://localhost:5173"

    # Constraints and Optimization Defaults
    RATE_LIMIT_PER_MINUTE: int = 10
    SOLVER_TIMEOUT_SECONDS: int = 5
    MAX_EVALUATION_RETRIES: int = 2
    DEFAULT_DISTANCE_PENALTY: float = 9999.0
    DEFAULT_FAIRNESS_SCORE: float = 0.5

    # Environment mode (development / staging / production)
    ENVIRONMENT: str = "development"

    def validate_production_secrets(self) -> None:
        """Log a warning if development fallback secrets are used in production."""
        import logging
        logger = logging.getLogger(__name__)
        if self.ENVIRONMENT.lower() == "production":
            if self.JWT_SECRET_KEY == "dev-secret-key-disaster-coordinator-change-in-production":
                logger.warning("SECURITY WARNING: Running in production with default JWT_SECRET_KEY!")
            if self.ENCRYPTION_KEY == "R2yIWPvAweDshbj20vqRMx6OQHEhptrQ5zkmx7ZLNVM=":
                logger.warning("SECURITY WARNING: Running in production with default ENCRYPTION_KEY!")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()

