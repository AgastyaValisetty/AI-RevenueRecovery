import argparse

from app.config import Settings
from app.container import build_database, build_orchestrator


def main() -> None:
    parser = argparse.ArgumentParser(description="People service orchestrator")
    parser.add_argument("--people", type=int, default=100)
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    settings = Settings.from_env()
    db = build_database(settings)
    if args.reset:
        db.drop_schema()
    db.create_schema()

    orchestrator = build_orchestrator(db, seed=args.seed)
    orchestrator.initialize(args.people)
    if args.days > 0:
        orchestrator.run_days(args.days)

    print(orchestrator.summary())


if __name__ == "__main__":
    main()
