"""Application settings for the People Service.

Re-exports simulation configuration classes from :mod:`config.simulation`
and provides the :class:`Settings` dataclass used for database / service
connection configuration.
"""

import os
from dataclasses import dataclass, field

from .simulation import (
    AgeConfig,
    CalibrationEntry,
    EcommerceConfig,
    EmploymentType,
    IncomeBracket,
    IncomeConfig,
    PaymentMethodConfig,
    PopulationConfig,
    SalaryConfig,
    SimulationConfig,
    SpendingConfig,
    SubscriptionConfig,
    TemporalConfig,
)
from .defaults import DEFAULT_CONFIG, DEFAULT_CONFIG_VERSION

DEFAULT_DB_PORT = 5433


@dataclass(frozen=True)
class LLMConfig:
    """NVIDIA NIM / LLM integration configuration for the Smart Recovery Agent.

    Controls the Nemotron model endpoint used for diagnosis, explanation,
    and message generation.  In replay mode, LLM responses are loaded from
    the audit trail rather than calling the API.
    """

    api_key: str | None = None
    base_url: str = "https://integrate.api.nvidia.com/v1"
    model_name: str = "nvidia/nemotron-3-super-120b-a12b"
    temperature: float = 0.2
    top_p: float = 0.95
    max_tokens: int = 2048
    # Mode: "live" = call NIM API, "replay" = reuse stored outputs, "fallback" = deterministic
    mode: str = "fallback"
    # Prompt version string for traceability
    prompt_version: str = "1.0.0"

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            api_key=os.getenv("NVIDIA_NIM_API_KEY"),
            base_url=os.getenv("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1"),
            model_name=os.getenv("NIM_MODEL_NAME", "nvidia/nemotron-3.5b-30b-a3b"),
            temperature=float(os.getenv("NIM_TEMPERATURE", "0.2")),
            top_p=float(os.getenv("NIM_TOP_P", "0.95")),
            max_tokens=int(os.getenv("NIM_MAX_TOKENS", "2048")),
            mode=os.getenv("NIM_MODE", "fallback"),
            prompt_version=os.getenv("NIM_PROMPT_VERSION", "1.0.0"),
        )

    @property
    def is_live(self) -> bool:
        return self.mode == "live" and self.api_key is not None


@dataclass(frozen=True)
class Settings:
    """Application settings loaded from environment variables.

    Used for database connection and inter-service communication configuration.
    """

    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_name: str
    lazerpay_url: str = "http://lazerpay_service:8001"
    bank_url: str = "http://bank_service:8002"
    http_timeout_seconds: float = 30.0
    llm: LLMConfig = field(default_factory=LLMConfig)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_host=os.getenv("DB_HOST", "localhost"),
            db_port=int(os.getenv("DB_PORT", str(DEFAULT_DB_PORT))),
            db_user=os.getenv("DB_USER", "simulator"),
            db_password=os.getenv("DB_PASSWORD", "simulator_dev"),
            db_name=os.getenv("DB_NAME", "revenue_recovery"),
            lazerpay_url=os.getenv("LAZERPAY_URL", "http://lazerpay_service:8001"),
            bank_url=os.getenv("BANK_URL", "http://bank_service:8002"),
            http_timeout_seconds=float(os.getenv("HTTP_TIMEOUT_SECONDS", "30.0")),
            llm=LLMConfig.from_env(),
        )

    @property
    def dsn(self) -> str:
        return (
            f"postgresql+psycopg2://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


__all__ = [
    "AgeConfig",
    "CalibrationEntry",
    "DEFAULT_CONFIG",
    "DEFAULT_CONFIG_VERSION",
    "EcommerceConfig",
    "EmploymentType",
    "IncomeBracket",
    "IncomeConfig",
    "LLMConfig",
    "PaymentMethodConfig",
    "PopulationConfig",
    "SalaryConfig",
    "Settings",
    "SimulationConfig",
    "SpendingConfig",
    "SubscriptionConfig",
    "TemporalConfig",
]
