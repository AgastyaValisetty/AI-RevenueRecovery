from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .schema import Base


class Database:
    def __init__(self, settings: Settings | None = None, engine_url: str | None = None):
        if engine_url is not None:
            self._engine = create_engine(engine_url, pool_pre_ping=True)
        elif settings is not None:
            self._engine = create_engine(settings.dsn, pool_pre_ping=True)
        else:
            raise ValueError("Either settings or engine_url must be provided")
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
