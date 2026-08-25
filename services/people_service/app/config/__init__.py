"""Application settings for the People Service.

Re-exports simulation configuration classes from :mod:`config.simulation`
and provides the :class:`Settings` dataclass used for database / service
connection configuration.
"""

import os
from dataclasses import dataclass

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
    http_timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_host=os.getenv("DB_HOST", "localhost"),
            db_port=int(os.getenv("DB_PORT", str(DEFAULT_DB_PORT))),
            db_user=os.getenv("DB_USER", "simulator"),
            db_password=os.getenv("DB_PASSWORD", "simulator_dev"),
            db_name=os.getenv("DB_NAME", "revenue_recovery"),
            lazerpay_url=os.getenv("LAZERPAY_URL", "http://lazerpay_service:8001"),
            http_timeout_seconds=float(os.getenv("HTTP_TIMEOUT_SECONDS", "30.0")),
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
    "PaymentMethodConfig",
    "PopulationConfig",
    "SalaryConfig",
    "Settings",
    "SimulationConfig",
    "SpendingConfig",
    "SubscriptionConfig",
    "TemporalConfig",
]
