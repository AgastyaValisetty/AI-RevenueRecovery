"""FastAPI dependency providers for the LazerPay Service."""
from fastapi import Request

from .database import Database
from .repos import LazerPayRepository


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_repo(request: Request) -> LazerPayRepository:
    db: Database = request.app.state.db
    return LazerPayRepository(db)
