"""pip-install safety net, run inside the backend container at every `up`.

Usage (from compose command:):
    python /tools/pip_install.py && exec uvicorn ...

Bind-mounted into each backend container at /tools/. Re-runs
`pip install -r requirements.txt` on every docker compose up so a stale
image never boots with missing dependencies.

Env:
    REQUIREMENTS_PATH  default /workspace/requirements.txt
"""
import os
import subprocess
import sys

REQUIREMENTS_PATH = os.environ.get("REQUIREMENTS_PATH", "/workspace/requirements.txt")


def main():
    if not os.path.exists(REQUIREMENTS_PATH):
        print(f"[pip-install] {REQUIREMENTS_PATH} not found, skipping", file=sys.stderr)
        sys.exit(0)
    print(f"[pip-install] installing {REQUIREMENTS_PATH}")
    result = subprocess.run(
        ["pip", "install", "--no-cache-dir", "-r", REQUIREMENTS_PATH],
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
