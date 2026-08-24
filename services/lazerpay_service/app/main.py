from fastapi import FastAPI

from .api import router
from .config import Settings
from .database import Database


def create_app() -> FastAPI:
    settings = Settings.from_env()
    db = Database(settings)
    db.create_schema()

    app = FastAPI(title="LazerPay Service", version="0.1.0")
    app.state.db = db
    app.include_router(router)
    return app


app = create_app()
