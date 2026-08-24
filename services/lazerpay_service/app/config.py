from dataclasses import dataclass
import os


DEFAULT_DB_PORT = 5433


@dataclass(frozen=True)
class Settings:
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_name: str
    bank_url: str
    service_port: int

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_host=os.getenv("DB_HOST", "localhost"),
            db_port=int(os.getenv("DB_PORT", str(DEFAULT_DB_PORT))),
            db_user=os.getenv("DB_USER", "simulator"),
            db_password=os.getenv("DB_PASSWORD", "simulator_dev"),
            db_name=os.getenv("DB_NAME", "revenue_recovery"),
            bank_url=os.getenv("BANK_URL", "http://localhost:8002"),
            service_port=int(os.getenv("LAZERPAY_PORT", "8001")),
        )

    @property
    def dsn(self) -> str:
        return (
            f"postgresql+psycopg2://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )