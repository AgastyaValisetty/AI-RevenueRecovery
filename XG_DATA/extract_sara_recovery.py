"""
extract_sara_recovery.py

Pulls every recovery action (baseline + SARA, lifetime + experiments) from
the people_service API and writes them to a single flat CSV.

Usage:
    python extract_sara_recovery.py                       # default: localhost:8000
    python extract_sara_recovery.py --out my_actions.csv
    python extract_sara_recovery.py --no-experiment       # lifetime only

Requires:
    pip install requests
"""

from __future__ import annotations

import argparse
import csv
import sys
from typing import Iterable

try:
    import requests
except ImportError:
    print("ERROR: 'requests' not installed. Run: pip install requests", file=sys.stderr)
    sys.exit(1)


# Output CSV columns — every API action field we care about, flattened.
# `engine` is added by this script from the engine_type filter used.
OUTPUT_COLUMNS = [
    "engine",
    "action_id",
    "run_id",
    "payment_intent_id",
    "related_attempt_id",
    "action_type",
    "retry_number",
    "scheduled_for",
    "executed_at",
    "created_at",
    "outcome",
    "reason",
    "schedule_reason",
    "failure_code",
    "failure_reason",
    "payment_method",
    "customer_declined",
    "amount",
    "cost",
    "expected_recovery",
    "metadata_json",
    "source",
]


def _normalize_row(raw: dict, engine: str, source: str) -> dict:
    out = {"engine": engine, "source": source}
    for col in OUTPUT_COLUMNS:
        if col in ("engine", "source"):
            continue
        v = raw.get(col)
        out[col] = "" if v is None else str(v)
    return out


def fetch_lifetime(session: requests.Session, base_url: str, engine: str) -> list[dict]:
    """Hit /api/recovery/actions for every outcome. `engine` is what we tag
    the rows with; the API itself is called WITHOUT an engine_type filter so
    we get both engines in a single pass, then we trust the engine filter to
    attribute the result correctly when needed.

    To get engine-distinguished rows we instead call twice (see fetch_engine
    below) and use this function for the un-filtered lifetime view."""
    all_rows: list[dict] = []
    for outcome in ("SUCCESS", "FAILED", "STOPPED", "PENDING"):
        try:
            resp = session.get(
                f"{base_url}/api/recovery/actions",
                params={"outcome": outcome, "limit": 5000},
                timeout=10,
            )
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as e:
            print(f"[lifetime/{engine}] WARN {outcome}: {e}", file=sys.stderr)
            continue
        except ValueError as e:
            print(f"[lifetime/{engine}] WARN {outcome} non-JSON: {e}", file=sys.stderr)
            continue
        rows = payload.get("actions") or []
        print(f"[lifetime/{engine}] {outcome}: {len(rows)} rows")
        for r in rows:
            r["_engine"] = engine
        all_rows.extend(rows)
    return all_rows


def fetch_engine(session: requests.Session, base_url: str, engine_type: str) -> list[dict]:
    """Hit /api/recovery/actions filtered by engine_type so rows are
    properly attributed to baseline or AI_AGENT."""
    all_rows: list[dict] = []
    for outcome in ("SUCCESS", "FAILED", "STOPPED", "PENDING"):
        try:
            resp = session.get(
                f"{base_url}/api/recovery/actions",
                params={
                    "outcome": outcome,
                    "engine_type": engine_type,
                    "limit": 5000,
                },
                timeout=10,
            )
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as e:
            print(f"[engine={engine_type}] WARN {outcome}: {e}", file=sys.stderr)
            continue
        except ValueError as e:
            print(f"[engine={engine_type}] WARN {outcome} non-JSON: {e}", file=sys.stderr)
            continue
        rows = payload.get("actions") or []
        print(f"[engine={engine_type}] {outcome}: {len(rows)} rows")
        for r in rows:
            r["_engine"] = engine_type
        all_rows.extend(rows)
    return all_rows


def fetch_parallel_experiment(
    session: requests.Session, base_url: str, experiment_id: str, engine: str
) -> list[dict]:
    """Pull retries from a preserved parallel experiment for one engine side."""
    try:
        resp = session.get(
            f"{base_url}/api/recovery/experiments/parallel/{experiment_id}/retries",
            params={"engine": engine, "limit": 5000},
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as e:
        print(f"[experiment/{experiment_id}/{engine}] WARN: {e}", file=sys.stderr)
        return []
    except ValueError as e:
        print(f"[experiment/{experiment_id}/{engine}] WARN non-JSON: {e}", file=sys.stderr)
        return []
    rows = payload.get("actions") or []
    print(f"[experiment/{experiment_id}/{engine}] {len(rows)} rows")
    for r in rows:
        r["_engine"] = engine
    return rows


def list_parallel_experiments(session: requests.Session, base_url: str) -> list[str]:
    try:
        resp = session.get(
            f"{base_url}/api/recovery/experiments/parallel/list",
            params={"limit": 20},
            timeout=10,
        )
        resp.raise_for_status()
        return [
            str(e.get("experiment_id") or e.get("id"))
            for e in (resp.json().get("experiments") or [])
            if e.get("experiment_id") or e.get("id")
        ]
    except requests.RequestException as e:
        print(f"[list] WARN: {e}", file=sys.stderr)
        return []


def health_check(session: requests.Session, base_url: str) -> bool:
    try:
        return session.get(f"{base_url}/api/simulation/status", timeout=5).ok
    except requests.RequestException:
        return False


def write_csv(rows: Iterable[dict], out_path: str) -> int:
    rows = list(rows)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return len(rows)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--out", default="sara_recovery_actions.csv")
    p.add_argument(
        "--no-experiment",
        action="store_true",
        help="skip pulling preserved parallel experiments",
    )
    args = p.parse_args()

    base_url = f"http://{args.host}:{args.port}"
    print(f"target API: {base_url}")
    session = requests.Session()

    if not health_check(session, base_url):
        print(
            f"ERROR: backend at {base_url} not reachable. "
            "Start the people_service first.",
            file=sys.stderr,
        )
        return 2

    # --- 1. Lifetime view, per engine ---
    # Two calls so each row is correctly attributed to baseline vs AI_AGENT.
    baseline = fetch_engine(session, base_url, "BASELINE")
    sara = fetch_engine(session, base_url, "AI_AGENT")
    print(f"[lifetime] baseline={len(baseline)}, sara={len(sara)}")

    # --- 2. Experiment view, per engine ---
    exp_rows: list[dict] = []
    if not args.no_experiment:
        exp_ids = list_parallel_experiments(session, base_url)
        for eid in exp_ids:
            for eng in ("baseline", "smart"):
                exp_rows.extend(fetch_parallel_experiment(session, base_url, eid, eng))
    print(f"[experiment] total rows: {len(exp_rows)}")

    # --- 3. Merge, dedupe on action_id ---
    merged: dict[str, dict] = {}

    def add(raw: dict, source: str) -> None:
        aid = str(raw.get("action_id") or "")
        if not aid:
            return
        engine = raw.get("_engine") or "unknown"
        merged[aid] = _normalize_row(raw, engine=engine, source=source)

    for r in baseline:
        add(r, source="lifetime")
    for r in sara:
        add(r, source="lifetime")
    for r in exp_rows:
        add(r, source="experiment")

    if not merged:
        print("No actions returned. Empty CSV written.", file=sys.stderr)

    n = write_csv(merged.values(), args.out)
    print(f"wrote {n} unique actions to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())