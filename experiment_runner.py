#!/usr/bin/env python
"""SARA Experiment Runner — CLI entry point for paired recovery experiments.

Runs a paired experiment comparing the BaselineRecoveryEngine against the
SmartRecoveryEngine (SARA) on identical seeded simulation state.

Usage::

    python experiment_runner.py           # 200 people, 72 hours, seed=42
    python experiment_runner.py --people 500 --hours 168 --seed 12345

Requires: PostgreSQL reachable at the configured DB settings (see env vars).
The PostgreSQL ``revenue_recovery`` database must already exist — the schema
is created dropped/recreated automatically by the experiment runner.

Output:
    - Console summary of baseline vs smart agent metrics.
    - ``experiments/`` directory with JSON + text reports.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# --- Bootstrap sys.path so we can import the people_service package --- #

REPO_ROOT = Path(__file__).resolve().parent
PPL_SVC_APP = REPO_ROOT / "services" / "people_service" / "app"
if str(PPL_SVC_APP) not in sys.path:
    sys.path.insert(0, str(PPL_SVC_APP.parent))  # so `from app import ...` works

# --- Imports from the people_service package --- #

from app.config import Settings  # noqa: E402
from app.database import Database  # noqa: E402
from app.recovery.smart_agent.experiment_runner import ExperimentRunner  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a SARA paired experiment: baseline vs Smart Agent.",
    )
    parser.add_argument(
        "--people", type=int, default=200,
        help="Number of people in the simulation (default: 200).",
    )
    parser.add_argument(
        "--hours", type=int, default=72,
        help="Number of simulation hours to run (default: 72).",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Root RNG seed for deterministic reproducibility (default: 42).",
    )
    parser.add_argument(
        "--output", type=str, default="./experiments",
        help="Directory to save reports (default: ./experiments).",
    )
    args = parser.parse_args()

    # Build settings + database
    settings = Settings.from_env()
    os.environ.setdefault("EXPERIMENT_OUTPUT_DIR", args.output)

    print(f"[experiment] Building database connection (host={settings.db_host}, port={settings.db_port})")
    db = Database(settings)
    db.create_schema()
    print("[experiment] Schema created.")

    # Build + run the experiment
    runner = ExperimentRunner(db=db, settings=settings)
    print(
        f"[experiment] Starting: {args.people} people, {args.hours}h, seed={args.seed}"
    )
    report = runner.run(
        people_count=args.people,
        hours=args.hours,
        seed=args.seed,
    )

    # Print summary
    print("\n" + "=" * 72)
    print("SARA Experiment — Results")
    print("=" * 72)
    print(json.dumps(report.to_dict(), indent=2, default=str))
    print("=" * 72)
    print(f"\nReports saved to: {args.output}/")
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
