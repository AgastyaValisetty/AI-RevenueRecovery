from fastapi import FastAPI

from .api import router
from .config import Settings
from .container import build_database, build_orchestrator
from .sim_config import SimConfig


def create_app() -> FastAPI:
    settings = Settings.from_env()
    config = SimConfig.defaults()
    db = build_database(settings)
    db.create_schema()

    app = FastAPI(title="People Service", version="0.1.0")
    app.state.settings = settings
    app.state.sim_config = config
    app.state.db = db
    app.state.orchestrator = build_orchestrator(
        db,
        seed=config.population.default_seed,
        config=config,
    )
    app.include_router(router)
    return app


app = create_app()
