from fastapi import FastAPI

from .api import router
from .config import Settings
from .container import build_database, build_orchestrator


def create_app() -> FastAPI:
    settings = Settings.from_env()
    db = build_database(settings)
    db.create_schema()

    app = FastAPI(title="People Service", version="0.1.0")
    app.state.orchestrator = build_orchestrator(db)
    app.include_router(router)
    return app


app = create_app()
