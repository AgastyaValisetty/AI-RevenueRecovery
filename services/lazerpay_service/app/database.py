"""Database setup for the LazerPay Service."""
from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import Pool

from .config import Settings
from .schema import BASE


class Database:
    def __init__(
        self,
        settings: Settings | None = None,
        engine_url: str | None = None,
        *,
        connect_args: dict[str, Any] | None = None,
        poolclass: type[Pool] | None = None,
    ):
        kwargs: dict[str, Any] = {"pool_pre_ping": True}
        if connect_args is not None:
            kwargs["connect_args"] = connect_args
        if poolclass is not None:
            kwargs["poolclass"] = poolclass

        if engine_url is not None:
            self._engine = create_engine(engine_url, **kwargs)
        elif settings is not None:
            self._engine = create_engine(settings.dsn, **kwargs)
        else:
            raise ValueError("Either settings or engine_url must be provided")
        self._session_factory = sessionmaker(
            bind=self._engine, expire_on_commit=False
        )

    def create_schema(self) -> None:
        """Create tables that this service owns.

        The ``payment_attempts`` table is shared with the People Service
        (which creates it on startup).  This service only needs to create
        ``idempotency_keys`` here.  ``create_all`` with ``checkfirst=True``
        will skip any table that already exists.
        """
        from .schema import IdempotencyKeyRow  # ensure table is registered
        try:
            BASE.metadata.create_all(
                self._engine,
                tables=[IdempotencyKeyRow.__table__],
                checkfirst=True,
            )
        except Exception:
            # Tables already exist (created by People Service) — safe to continue.
            pass

    def drop_schema(self) -> None:
        BASE.metadata.drop_all(self._engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def health_check(self) -> bool:
        """Return True if the database is reachable."""
        try:
            with self._engine.connect() as conn:
                conn.exec_driver_sql("SELECT 1")
            return True
        except Exception:
            return False
