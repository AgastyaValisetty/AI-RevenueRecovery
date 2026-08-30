from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event, text
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


class SchemaScopedDatabase(Database):
    """A :class:`Database` that operates inside an isolated PostgreSQL schema.

    Uses ``SET search_path`` so that SQLAlchemy tables resolve to
    ``<schema_name>.<table>``.  This allows two orchestrators to share a single
    PostgreSQL database while keeping their data fully isolated in separate
    schemas — ideal for parallel baseline-vs-smart-agent experiments.

    Each schema-scoped database creates and drops its tables within the
    configured schema namespace, so there is no cross-engine data leakage.

    Parameters
    ----------
    settings / engine_url :
        Same as :class:`Database`.
    schema_name :
        The PostgreSQL schema to use (e.g. ``baseline_run``, ``smart_run``).
    """

    def __init__(
        self,
        settings: Settings | None = None,
        engine_url: str | None = None,
        schema_name: str = "public",
    ):
        super().__init__(settings=settings, engine_url=engine_url)
        self._schema_name = schema_name

        @event.listens_for(self._engine, "connect")
        def _set_search_path(dbapi_conn, _record):
            # Set search_path on the raw DBAPI connection so every SQLAlchemy
            # operation (incl. CREATE TABLE / DROP) runs inside the schema.
            # psycopg2 connections require a cursor to execute raw SQL.
            cursor = dbapi_conn.cursor()
            cursor.execute(f"SET search_path TO {schema_name}")
            cursor.close()

        # Ensure the schema itself exists
        with self._engine.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))
            conn.execute(text(f"SET search_path TO {schema_name}"))

    def create_schema(self) -> None:
        """Create all tables inside this database's schema namespace."""
        Base.metadata.create_all(self._engine)

    def drop_schema(self) -> None:
        """Drop all tables inside this database's schema namespace."""
        Base.metadata.drop_all(self._engine)

    def drop_schema_only(self) -> None:
        """Drop the PostgreSQL schema itself (including all objects)."""
        with self._engine.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {self._schema_name} CASCADE"))

    def create_schema_only(self) -> None:
        """Create the PostgreSQL schema (tables are created via create_schema)."""
        with self._engine.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {self._schema_name}"))
