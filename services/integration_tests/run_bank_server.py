"""Run the Bank Service as a standalone HTTP server with SQLite backend.

This script is executed as a **subprocess** from conftest.py to avoid the
``app`` package name conflict between the Bank Service and LazerPay Service
(which both live in an ``app/`` directory).

Usage::

    python run_bank_server.py <db_url> <port>

The Bank Service tables (``banks``, ``bank_accounts``, ``ledger_entries``,
``bank_metrics``) are created beforehand by the integration-test conftest,
so this runner only needs to wire up the app and start uvicorn.
"""
import sys
from pathlib import Path

# Make the Bank Service's ``app`` package importable on its own.
_BANK_SERVICE_DIR = Path(__file__).resolve().parent.parent / "bank_service"
sys.path.insert(0, str(_BANK_SERVICE_DIR))

import uvicorn
from fastapi import FastAPI

from app.config import Settings
from app.database import Database
from app.api import router


def main() -> None:
    db_url = sys.argv[1]
    port = int(sys.argv[2])

    # The Bank Service's Database accepts engine_url directly, bypassing
    # the PostgreSQL-only Settings.dsn property.
    db = Database(
        engine_url=db_url,
        connect_args={"check_same_thread": False, "timeout": 30.0},
    )

    settings = Settings(
        db_host="test",
        db_port=5432,
        db_user="test",
        db_password="test",
        db_name="test",
        service_port=port,
    )

    app = FastAPI(title="Bank Service", version="1.0.0")
    app.state.db = db
    app.state.settings = settings
    app.include_router(router)

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
