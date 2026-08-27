import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote_plus

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Configuracion central. Los secretos solo se leen desde el entorno/.env."""

    APP_NAME: str = "DrapeMind API"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: Literal["development", "test", "production"] = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    DOCS_ENABLED: bool = True
    SECRET_KEY: str = "change-me-with-at-least-32-characters"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    DATABASE_URL: str | None = None
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "drapemind_db"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_ECHO: bool = False
    CORS_ORIGINS: list[str] = ["http://localhost:4200", "http://127.0.0.1:4200"]
    CORS_ORIGIN_REGEX: str | None = None
    CORS_ALLOW_CREDENTIALS: bool = True
    AI_BASE_URL: str = "http://localhost:8080/v1"
    AI_API_KEY: str = "local-no-key"
    AI_MODEL: str = "google/gemma-4-E2B-it-qat-q4_0-gguf"
    AI_MANAGED_SERVER: bool = True
    AI_SERVER_HOST: str = "127.0.0.1"
    AI_SERVER_PORT: int = 8080
    AI_MODEL_PATH: str = "ai_models/gemma-4-e2b/gemma-4-E2B_q4_0-it.gguf"
    AI_MMPROJ_PATH: str = "ai_models/gemma-4-e2b/gemma-4-E2B-it-mmproj.gguf"
    LLAMA_SERVER_PATH: str | None = None
    AI_IDLE_TIMEOUT_SECONDS: int = 600
    AI_STARTUP_TIMEOUT_SECONDS: int = 240
    AI_CONTEXT_SIZE: int = 8192
    AI_PARALLEL_SLOTS: int = 2
    AI_THREADS: int = 0
    AI_GPU_LAYERS: str = "auto"
    AI_SERVER_EXTRA_ARGS: str = ""
    AI_MAX_AGENT_STEPS: int = 4
    AI_TIMEOUT_SECONDS: float = 90.0
    AI_MAX_TOKENS: int = 1024
    AI_TEMPERATURE: float = 0.35
    RESERVATION_TTL_MINUTES: int = 30
    PAYMENT_PROVIDER: Literal["mock", "external"] = "mock"
    PAYMENT_WEBHOOK_SECRET: str = "change-me-payment-webhook-secret"
    AR_ASSET_BASE_URL: str = "http://localhost:8000/static/ar"

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("["):
                return json.loads(value)
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("CORS_ORIGINS")
    @classmethod
    def normalize_cors_origins(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(origin.rstrip("/") for origin in value))

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.ENVIRONMENT == "production":
            if self.SECRET_KEY.startswith("change-me") or len(self.SECRET_KEY) < 32:
                raise ValueError("SECRET_KEY debe ser aleatoria y tener al menos 32 caracteres")
            if self.PAYMENT_WEBHOOK_SECRET.startswith("change-me") or len(self.PAYMENT_WEBHOOK_SECRET) < 24:
                raise ValueError("PAYMENT_WEBHOOK_SECRET debe ser aleatorio en produccion")
            if "*" in self.CORS_ORIGINS and self.CORS_ALLOW_CREDENTIALS:
                raise ValueError("CORS no puede usar '*' con credenciales en produccion")
        return self

    @property
    def database_uri(self) -> str:
        if self.DATABASE_URL:
            url = self.DATABASE_URL
            if url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+psycopg://", 1)
            elif url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql+psycopg://", 1)
            return url
        user = quote_plus(self.POSTGRES_USER)
        password = quote_plus(self.POSTGRES_PASSWORD)
        return (
            f"postgresql+psycopg://{user}:{password}@"
            f"{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    model_config = SettingsConfigDict(
        env_file=(str(BACKEND_DIR / ".env"), ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
