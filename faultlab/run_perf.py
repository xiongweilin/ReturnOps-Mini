"""播种一个组织，然后在 faultlab 栈里跑 k6 性能契约。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = Path(__file__).resolve().parent / "docker-compose.faultlab.yml"
API_HEALTH_URL = "http://127.0.0.1:8000/health"
API_READY_TIMEOUT_SECONDS = 60


def wait_for_api_ready() -> None:
    """Wait for the fault-lab API to answer its real HTTP health endpoint."""
    deadline = time.monotonic() + API_READY_TIMEOUT_SECONDS
    last_error = "no HTTP response received"

    while True:
        try:
            with urlopen(API_HEALTH_URL, timeout=2) as response:
                body = json.load(response)
                if (
                    response.status == 200
                    and isinstance(body, dict)
                    and body.get("status") == "ok"
                ):
                    print(f"API HTTP readiness confirmed: {API_HEALTH_URL}", flush=True)
                    return
                last_error = f"unexpected response: HTTP {response.status}, body={body!r}"
        except (OSError, ValueError) as exc:
            last_error = str(exc)

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(1, remaining))

    raise TimeoutError(
        f"API did not become HTTP-ready at {API_HEALTH_URL} within "
        f"{API_READY_TIMEOUT_SECONDS}s: {last_error}"
    )


def main() -> int:
    seed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent / "seed_context.py")],
        capture_output=True,
        text=True,
        check=True,
    )
    context = dict(line.split("=", 1) for line in seed.stdout.strip().splitlines() if "=" in line)
    print(seed.stdout.strip())
    # compose 的 ${K6_ORG_ID} 在宿主机解析，所以变量必须进子进程环境，
    # 而不是用 `docker compose run -e`（那只影响容器内部）。
    env = {**os.environ, "K6_ORG_ID": context["ORG_ID"], "K6_ORG_TOKEN": context["ORG_TOKEN"]}
    wait_for_api_ready()
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "run", "--no-deps", "--rm", "k6"],
        check=False,
        env=env,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
