"""Bank Service application entry point."""
from fastapi import FastAPI

from .api import router
from .config import Settings
from .database import Database


def create_app() -> FastAPI:
    settings = Settings.from_env()
    db = Database(settings)
    db.create_schema()

    app = FastAPI(title="Bank Service", version="1.0.0")
    app.state.db = db
    app.state.settings = settings
    app.include_router(router)
    return app


app = create_app()
