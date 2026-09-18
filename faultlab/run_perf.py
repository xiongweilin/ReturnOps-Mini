"""播种一个组织，然后在 faultlab 栈里跑 k6 性能契约。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = Path(__file__).resolve().parent / "docker-compose.faultlab.yml"


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
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "run", "--rm", "k6"],
        check=False,
        env=env,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
