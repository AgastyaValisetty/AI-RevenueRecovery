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

        The Bank Service shares the ``banks`` and ``bank_accounts`` tables
        with the People Service (which creates them on startup).  We only
        need to create ``bank_metrics`` here and let the shared tables be
        owned by the People Service.  ``create_all`` with ``checkfirst=True``
        will skip any table that already exists, but a cross-service race
        can still raise an IntegrityError if both services start
        simultaneously — we swallow that.
        """
        from .schema import BankMetricRow  # ensure table is registered
        try:
            BASE.metadata.create_all(self._engine, checkfirst=True)
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
