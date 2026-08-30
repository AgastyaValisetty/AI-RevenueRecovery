#!/usr/bin/env python3
"""Run a Parallel Experiment end-to-end from the command line.

Usage:
    python run_parallel_experiment.py --people 200 --hours 72 --seed 42

Requires:
    - PostgreSQL running (docker-compose)
    - DB_HOST=postgres (or set DB_HOST to localhost if running locally)
    - NVIDIA_NIM_API_KEY (optional — defaults to fallback mode if not set)
"""
import argparse
import sys

# Ensure stdout uses UTF-8 to handle Unicode characters in output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.config import Settings
from app.database import Database
from app.recovery.smart_agent.parallel_runner import ParallelExperimentRunner


def main():
    parser = argparse.ArgumentParser(description="Run a parallel SARA experiment")
    parser.add_argument("--people", type=int, default=200, help="Number of people to simulate")
    parser.add_argument("--hours", type=int, default=72, help="Number of simulation hours")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    parser.add_argument("--keep-schemas", action="store_true", default=True,
                        help="Keep schemas after run for case exploration")
    parser.add_argument("--cleanup", action="store_true", default=False,
                        help="Drop schemas after run (default: keep them)")
    args = parser.parse_args()

    settings = Settings.from_env()
    db = Database(settings)

    # Ensure the public schema has tables (for the base Database)
    db.create_schema()

    runner = ParallelExperimentRunner(db, settings)
    print(f"Starting parallel experiment: {args.people} people, {args.hours} hours, seed={args.seed}")
    print(f"DB host: {settings.db_host}:{settings.db_port}/{settings.db_name}")
    print(f"LLM mode: {settings.llm.mode}")

    report = runner.run(
        people_count=args.people,
        hours=args.hours,
        seed=args.seed,
        keep_schemas=not args.cleanup,
    )

    print("\n" + "=" * 72)
    print("EXPERIMENT COMPLETE")
    print("=" * 72)

    b = report.baseline
    s = report.smart
    lift = report

    print(f"\nBaseline: {b.total_cases} cases, {b.recovered_cases} recovered, "
          f"net={b.net_recovered_value} INR")
    print(f"Smart:    {s.total_cases} cases, {s.recovered_cases} recovered, "
          f"net={s.net_recovered_value} INR")
    print(f"\nLift:")
    print(f"  Incremental net recovered: {lift.incremental_recovered_value} INR")
    print(f"  Recovery rate lift:        {lift.incremental_recovery_rate:+.2f} pp")
    print(f"  Wasted retries saved:      {lift.wasted_retry_reduction}")
    print(f"  Cost savings:              {lift.total_cost_savings} INR")
    print(f"\nNotes: {report.notes}")

    # List saved reports
    experiments = runner.list_experiments(limit=10)
    if experiments:
        print(f"\nRecent experiments ({len(experiments)} found):")
        for exp in experiments:
            print(f"  {exp['experiment_id']}: baseline={exp['baseline_cases']}, "
                  f"smart={exp['smart_cases']}, lift={exp['lift']} INR")

    db._engine.dispose()
    print("\nDone. Reports saved to ./experiments/")


if __name__ == "__main__":
    main()
