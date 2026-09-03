"""Reset all database tables (including ledger, recovery, payment attempts,
parallel-experiment schemas, and on-disk experiment reports).

Run from the services/people_service directory:
    python reset_db.py

This wipes:
  1. The main schema (ledger, recovery, payment attempts, simulation runs, etc.)
  2. Any preserved ``exp_*_baseline`` / ``exp_*_smart`` parallel-experiment
     schemas left behind by the comparison runner.  Without this, the SARA
     tab keeps showing data from a previous run because it prefers the
     parallel schema view over the lifetime metrics view.
  3. The JSON/TXT reports under ``EXPERIMENT_OUTPUT_DIR`` (defaults to
     ``./experiments``), which ``listParallelExperiments`` reads to populate
     the comparison page history.
"""
import sys
from pathlib import Path

sys.path.insert(0, '.')
from sqlalchemy import text

from app.config import Settings
from app.database import Database


PARALLEL_SCHEMA_PREFIX = 'exp_'  # matches ParallelExperimentRunner._schema_prefix
DEFAULT_EXPERIMENT_DIR = './experiments'


def _drop_parallel_schemas(db: Database) -> int:
    """Drop every PostgreSQL schema whose name starts with ``exp_``.

    Returns the number of schemas dropped.

    Each schema is dropped in its own autocommit transaction so locks are
    released between drops — running dozens of CASCADE drops in a single
    transaction exhausts PostgreSQL's ``max_locks_per_transaction`` and
    fails with ``Out of shared memory``.
    """
    dropped = 0
    # Autocommit isolation so each DROP SCHEMA ... CASCADE commits its locks
    # immediately instead of holding them all until the outer transaction
    # finishes.
    with db._engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        rows = conn.execute(
            text(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name LIKE :prefix ORDER BY schema_name"
            ),
            {'prefix': f'{PARALLEL_SCHEMA_PREFIX}%'},
        ).fetchall()
        for (schema_name,) in rows:
            try:
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
                dropped += 1
            except Exception as exc:
                # Don't let a single failed drop (e.g. permission issue)
                # stop the reset — surface the failure and keep going.
                print(f'  ! failed to drop schema "{schema_name}": {exc}')
    return dropped


def _wipe_experiment_reports(experiment_dir: Path) -> int:
    """Delete every ``parallel_*.json`` / ``parallel_*.txt`` file under
    ``experiment_dir``.  Returns the number of files removed.
    """
    if not experiment_dir.exists():
        return 0
    removed = 0
    for pattern in ('parallel_*.json', 'parallel_*.txt'):
        for path in experiment_dir.glob(pattern):
            try:
                path.unlink()
                removed += 1
            except OSError as exc:
                print(f'  ! could not delete {path}: {exc}')
    return removed


def reset_database():
    settings = Settings.from_env()
    db = Database(settings)

    # 1) Main schema
    db.drop_schema()
    db.create_schema()
    print('Database reset - main schema dropped and recreated empty')

    # 2) Preserved parallel-experiment schemas
    dropped = _drop_parallel_schemas(db)
    if dropped:
        print(f'Dropped {dropped} preserved parallel-experiment schema(s) '
              f'({PARALLEL_SCHEMA_PREFIX}*)')

    # 3) On-disk experiment reports
    import os
    exp_dir = Path(os.environ.get('EXPERIMENT_OUTPUT_DIR', DEFAULT_EXPERIMENT_DIR))
    removed = _wipe_experiment_reports(exp_dir)
    if removed:
        print(f'Removed {removed} experiment report file(s) from {exp_dir}/')

    return db


if __name__ == '__main__':
    reset_database()