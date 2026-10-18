import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote_plus

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Configuracion central. Los secretos solo se leen desde el entorno/.env."""

    APP_NAME: str = "DrapeMind API"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: Literal["development", "test", "production"] = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    ROOT_PATH: str = ""
    PORT: int = 8000
    DOCS_ENABLED: bool = True
    SECRET_KEY: str = "change-me-with-at-least-32-characters"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 5256000  # 10 anos: sesion permanente estilo Facebook
    DATABASE_URL: str | None = None
    RUNTIME_DATABASE_URL: str | None = None
    SAAS_WEB_URL: str = 'http://localhost:4200'
    STRIPE_SAAS_WEBHOOK_SECRET: str = ''
    STRIPE_LOCAL_WEBHOOK_SECRET: str = ''
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
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    NVIDIA_API_KEY: str = ""
    NVIDIA_MODEL: str = "nvidia/nemotron-3-super-120b-a12b"
    NVIDIA_EXTRA_BODY: dict[str, Any] = Field(default_factory=lambda: {"chat_template_kwargs": {"enable_thinking": False}})
    AI_MAX_TOOL_ROUNDS: int = Field(default=3, ge=1, le=6)
    AI_MAX_TOOL_CALLS: int = Field(default=8, ge=1, le=20)
    STORE_POLICIES: dict[str, str] = Field(default_factory=dict)
    AI_TURN_TIMEOUT_SECONDS: float = Field(default=120, ge=15, le=300)
    AI_AGENT_DEADLINE_SECONDS: float = Field(default=90, ge=10, le=300)
    AI_TIMEOUT_SECONDS: float = 60.0
    AI_MAX_TOKENS: int = 1024
    AI_TEMPERATURE: float = 0.35
    RESERVATION_TTL_MINUTES: int = 2880
    PAYMENT_PROVIDER: Literal["mock", "external", "stripe"] = "mock"
    PAYMENT_WEBHOOK_SECRET: str = "change-me-payment-webhook-secret"
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    AR_ASSET_BASE_URL: str = "http://localhost:8000/static/ar"
    FCM_SERVER_KEY: str | None = None
    FIREBASE_CREDENTIALS_PATH: str | None = None
    FIREBASE_PROJECT_ID: str = "drapemind-5bd6e"

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
    def llm_base_url(self) -> str:
        return self.NVIDIA_BASE_URL.rstrip("/")

    @property
    def llm_api_key(self) -> str:
        return self.NVIDIA_API_KEY

    @property
    def llm_model(self) -> str:
        return self.NVIDIA_MODEL

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
