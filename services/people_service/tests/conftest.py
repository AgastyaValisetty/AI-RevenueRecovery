"""Shared pytest fixtures for the People Service test suite.

All database-backed tests use an in-memory SQLite database so no
external PostgreSQL service is required.
"""

from __future__ import annotations

import sys
import os
from decimal import Decimal
from uuid import uuid4

import pytest

# Ensure the app package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import Settings  # noqa: E402
from app.database import Database  # noqa: E402
from app.rng import SimulationRNG  # noqa: E402
from app.sim_config import SimConfig  # noqa: E402


@pytest.fixture
def db() -> Database:
    """An in-memory SQLite database with schema created."""
    database = Database(engine_url="sqlite:///:memory:")
    database.create_schema()
    return database


@pytest.fixture
def config() -> SimConfig:
    """The default SimConfig shipped with the service."""
    return SimConfig.defaults()


@pytest.fixture
def rng() -> SimulationRNG:
    """A SimulationRNG seeded with 42 for deterministic tests."""
    return SimulationRNG(42)
