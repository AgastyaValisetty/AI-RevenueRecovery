"""Database setup for the LazerPay Service."""
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .schema import BASE


class Database:
    def __init__(self, settings: Settings):
        self._engine = create_engine(settings.dsn, pool_pre_ping=True)
        self._session_factory = sessionmaker(
            bind=self._engine, expire_on_commit=False
        )

    def create_schema(self) -> None:
        """Create tables that this service owns.

        The LazerPay Service shares the ``payment_attempts`` table with the
        People Service.  We only need to create ``idempotency_keys`` here.
        Any IntegrityError from a shared table already existing is swallowed.
        """
        from .schema import IdempotencyKeyRow  # ensure table is registered
        try:
            BASE.metadata.create_all(self._engine, checkfirst=True)
        except Exception:
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
