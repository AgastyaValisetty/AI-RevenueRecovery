"""master.py — boot the whole AI-RevenueRecovery stack from a single command.

Starts PostgreSQL (via docker compose), then launches the three FastAPI
services each on its own port, wires their inter-service URLs together,
optionally seeds a simulation run, and cleanly shuts everything down on
Ctrl+C.

    Services                      Port
    ----------------------------  ----
    people_service   (simulation) 8000
    lazerpay_service (gateway)    8001
    bank_service     (RupeeBank)  8002
    postgres         (docker)     5433

Usage::

    python master.py              # boot everything, seed a 100-person run
    python master.py --init 0     # boot everything, don't seed
    python master.py --init 250   # seed a 250-person run

Requires: Docker (with the `postgres` compose service) and the same
Python environment that has fastapi/uvicorn/sqlalchemy installed.

Exit codes: 0 on clean shutdown, 1 on startup failure.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_HOST = "localhost"
DB_PORT = 5433
DB_USER = "simulator"
DB_PASSWORD = "simulator_dev"
DB_NAME = "revenue_recovery"

COMMON_DB_ENV = {
    "DB_HOST": DB_HOST,
    "DB_PORT": str(DB_PORT),
    "DB_USER": DB_USER,
    "DB_PASSWORD": DB_PASSWORD,
    "DB_NAME": DB_NAME,
}

# name -> (cwd relative to REPO_ROOT, port, extra env)
SERVICES = {
    "people": (
        "services/people_service",
        8000,
        {"LAZERPAY_URL": "http://localhost:8001", "HTTP_TIMEOUT_SECONDS": "30.0"},
    ),
    "bank": (
        "services/bank_service",
        8002,
        {"BANK_PORT": "8002"},
    ),
    "lazerpay": (
        "services/lazerpay_service",
        8001,
        {
            "BANK_URL": "http://localhost:8002",
            "LAZERPAY_PORT": "8001",
            "HTTP_TIMEOUT_SECONDS": "10.0",
        },
    ),
}

POSTGRES_UP_TIMEOUT_S = 90  # allow time for the postgres image to be pulled/started
SERVICE_UP_TIMEOUT_S = 60


def resolve_compose_cmd() -> list[str]:
    """Return the compose command (['docker-compose'] or ['docker', 'compose'])."""
    docker_compose = shutil.which("docker-compose")
    if docker_compose:
        return [docker_compose]
    docker = shutil.which("docker")
    if docker:
        return [docker, "compose"]
    raise RuntimeError(
        "Neither 'docker-compose' nor 'docker compose' was found on PATH. "
        "Install Docker to use master.py (or run services manually)."
    )


# ---------------------------------------------------------------------------
# Postgres bootstrap
# ---------------------------------------------------------------------------


def is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_for_db(timeout: float = POSTGRES_UP_TIMEOUT_S) -> None:
    dead = time.time() + timeout
    while time.time() < dead:
        if is_port_open(DB_HOST, DB_PORT, timeout=1.0):
            return
        time.sleep(2)
    raise RuntimeError(
        f"PostgreSQL did not become reachable on {DB_HOST}:{DB_PORT} "
        f"within {timeout}s. Check `docker compose ps` for the postgres container."
    )


def ensure_postgres() -> None:
    if is_port_open(DB_HOST, DB_PORT, timeout=1.0):
        print(f"[postgres] already reachable on {DB_HOST}:{DB_PORT}")
        return

    compose = resolve_compose_cmd()
    print(f"[postgres] starting via {compose[0]} up -d postgres ...")
    res = subprocess.run(
        [*compose, "up", "-d", "postgres"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        raise RuntimeError(
            "Failed to start postgres container:\n"
            f"stdout: {res.stdout}\nstderr: {res.stderr}"
        )
    print("[postgres] waiting for the database to accept connections ...")
    wait_for_db()


# ---------------------------------------------------------------------------
# Windows Job Object — kill children when the parent dies
# ---------------------------------------------------------------------------


def _install_windows_job() -> object | None:
    """On Windows, join this process and all its children into a Job Object
    configured with ``KILL_ON_JOB_CLOSE``.

    This guarantees that if the master process is killed or exits unexpectedly,
    every launched service subprocess is terminated with it — no orphans.  It is
    a no-op on non-Windows platforms and returns the job handle (kept alive for
    the process lifetime) or ``None``.
    """
    if os.name != "nt":
        return None

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    kernel32.SetInformationJobObject(
        job, 9, ctypes.byref(info), ctypes.sizeof(info)
    )
    return int(job)


def _assign_to_job(job: object | None) -> None:
    """Assign the current process to the job object created by ``_install_windows_job``.

    The master process and every child it spawns inherit the job handle, so
    when the master is terminated the whole tree is killed together.
    """
    if job is None or os.name != "nt":
        return
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.AssignProcessToJobObject(
        ctypes.c_void_p(job), ctypes.c_void_p(_current_pid_handle())
    )


def _current_pid_handle() -> int:
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    return int(kernel32.GetCurrentProcess())


# ---------------------------------------------------------------------------
# Service subprocess management
# ---------------------------------------------------------------------------


class ServiceProcess:
    """A managed uvicorn subprocess with prefixed, line-buffered logging."""

    def __init__(self, name: str, dir_rel: str, port: int, extra_env: dict):
        self.name = name
        self.cwd = REPO_ROOT / dir_rel
        self.port = port
        self.extra_env = extra_env
        self.proc: subprocess.Popen | None = None
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        env = {**os.environ, **COMMON_DB_ENV, **self.extra_env}
        env["PYTHONUNBUFFERED"] = "1"
        self.proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
            ],
            cwd=str(self.cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._threads.append(
            threading.Thread(
                target=self._pipe_reader,
                args=(self.proc.stdout, f"[{self.name}] "),
                daemon=True,
            )
        )
        self._threads.append(
            threading.Thread(
                target=self._pipe_reader,
                args=(self.proc.stderr, f"[{self.name}:err] "),
                daemon=True,
            )
        )
        for t in self._threads:
            t.start()

    @staticmethod
    def _pipe_reader(fh, prefix: str) -> None:
        if fh is None:
            return
        for line in fh:
            print(f"{prefix}{line}", end="", flush=True)

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        if self.proc is None:
            return
        if self.proc.poll() is None:
            print(f"[master] stopping {self.name} ...")
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)


ACTIVE_SERVICES: list[ServiceProcess] = []


def stop_all() -> None:
    for svc in reversed(ACTIVE_SERVICES):
        svc.stop()
    ACTIVE_SERVICES.clear()


def poll_service_health() -> bool:
    """Return True once the People Service status endpoint is up.

    Starts everyone, but blocks only on People Service (which owns schema
    creation and seeds the shared tables). Bank/LazerPay schemas are created
    lazily per-process and reachable almost immediately after import.
    """
    import urllib.request

    dead = time.time() + SERVICE_UP_TIMEOUT_S
    while time.time() < dead:
        for svc in ACTIVE_SERVICES:
            if not svc.is_running():
                print(
                    f"[master] {svc.name} exited early with code "
                    f"{svc.proc.returncode if svc.proc else '?'}",
                    flush=True,
                )
                return False
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:8000/api/simulation/status", timeout=2
            ) as resp:
                if resp.status == 200:
                    print("[master] all services are up", flush=True)
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


def seed_simulation(people_count: int) -> None:
    """Create an initial simulation run (bank, merchants, people, subscriptions)."""
    import json
    import urllib.request

    payload = json.dumps({"people_count": people_count, "hours": 0}).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/simulation/run",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode())
        summary = body.get("summary", {})
        run_id = summary.get("run_id") or body.get("run_id")
        print(
            "[master] seeded simulation run "
            f"(people={summary.get('people')}, run_id={run_id})",
            flush=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[master] WARNING: seeding failed ({exc})", flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Boot the full service stack.")
    parser.add_argument(
        "--init",
        nargs="?",
        const=100,
        type=int,
        default=100,
        help="Seed a simulation run with this many people (default 100). "
        "Pass --init 0 to disable seeding.",
    )
    args = parser.parse_args()

    # On Windows, join the master + all service children into a Job Object so
    # the children are killed automatically if the master dies unexpectedly.
    _job = _install_windows_job()
    _assign_to_job(_job)

    try:
        print("=== AI-RevenueRecovery master launcher ===", flush=True)
        ensure_postgres()

        for name, (rel, port, extra) in SERVICES.items():
            svc = ServiceProcess(name, rel, port, extra)
            print(
                f"[master] starting {name} on http://127.0.0.1:{port} ...",
                flush=True,
            )
            svc.start()
            ACTIVE_SERVICES.append(svc)

        if not poll_service_health():
            print("[master] startup failed — see logs above.", flush=True)
            stop_all()
            return 1

        if args.init and args.init > 0:
            seed_simulation(args.init)

        print("\n=== All services running ===", flush=True)
        print("  People:   http://127.0.0.1:8000/api/simulation/status", flush=True)
        print("  LazerPay: http://127.0.0.1:8001/api/status", flush=True)
        print("  Bank:     http://127.0.0.1:8002/api/status", flush=True)
        print("  Postgres: localhost:5433 (via docker)", flush=True)
        print("\nPress Ctrl+C to stop all services.\n", flush=True)

    except KeyboardInterrupt:
        print("\n[master] interrupt received, shutting down ...", flush=True)
        stop_all()
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[master] ERROR: {exc}", file=sys.stderr, flush=True)
        stop_all()
        return 1

    # Block in the foreground so Ctrl+C reaches this process.
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[master] interrupt received, shutting down ...", flush=True)
        stop_all()
        return 0


if __name__ == "__main__":
    sys.exit(main())
