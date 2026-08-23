from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .schema import Base


class Database:
    def __init__(self, settings: Settings):
        self._engine = create_engine(settings.dsn, pool_pre_ping=True)
        self._session_factory = sessionmaker(
            bind=self._engine, expire_on_commit=False
        )

    def create_schema(self) -> None:
        Base.metadata.create_all(self._engine)

    def drop_schema(self) -> None:
        Base.metadata.drop_all(self._engine)

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
