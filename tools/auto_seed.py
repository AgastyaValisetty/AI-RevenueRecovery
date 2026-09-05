"""Wait for people_service, then POST /api/simulation/run with seed.

Runs in a sidecar container. Polls GET /api/simulation/status until 200,
then either posts a new /api/simulation/run (if population is empty) or
exits silently (if the population is already seeded).

Env:
    PEOPLE_URL    default http://localhost:8000
    SEED          default 42
    PEOPLE_COUNT  default 100
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("PEOPLE_URL", "http://localhost:8000").rstrip("/")
SEED = int(os.environ.get("SEED", "42"))
PEOPLE_COUNT = int(os.environ.get("PEOPLE_COUNT", "100"))


def http_get(url, timeout=2):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read()
    except Exception:
        return None, None


def wait_ready():
    """Poll /api/simulation/status until 200 or 60s timeout."""
    deadline = time.time() + 60
    while time.time() < deadline:
        status, _ = http_get(f"{BASE}/api/simulation/status", timeout=2)
        if status == 200:
            return True
        time.sleep(2)
    return False


def already_seeded():
    """Check if the population is already seeded. The backend returns 200
    even for an empty DB, so we look at the length of the people list."""
    status, body = http_get(f"{BASE}/api/people", timeout=5)
    if status != 200 or not body:
        return False
    data = json.loads(body)
    return bool(data.get("people"))


def post_run():
    """POST /api/simulation/run with the configured seed and people count."""
    payload = json.dumps({
        "people_count": PEOPLE_COUNT,
        "days": 0,
        "hours": 0,
        "seed": SEED,
        "enable_recovery": True,
    }).encode()
    req = urllib.request.Request(
        f"{BASE}/api/simulation/run",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.status, r.read().decode()


def main():
    if not wait_ready():
        print("[auto-seed] people_service not ready, giving up", file=sys.stderr)
        sys.exit(1)
    if already_seeded():
        print("[auto-seed] population already seeded, skipping")
        return
    try:
        status, _body = post_run()
    except urllib.error.HTTPError as e:
        print(f"[auto-seed] HTTP {e.code}: {e.read().decode()}", file=sys.stderr)
        sys.exit(1)
    print(f"[auto-seed] OK seed={SEED} people={PEOPLE_COUNT} status={status}")


if __name__ == "__main__":
    main()
