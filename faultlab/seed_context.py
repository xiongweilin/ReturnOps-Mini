"""为性能契约准备一个已播种的组织，输出 ORG_ID / ORG_TOKEN。"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault(
    "RETURNOPS_DATABASE_URL",
    "postgresql+psycopg://returnops:returnops@127.0.0.1:5432/returnops",
)

from faultlab.scenarios import make_session  # noqa: E402
from returnops.domain.states import Role  # noqa: E402
from tests.conftest import seed_organization  # noqa: E402


def main() -> int:
    engine, session_factory = make_session(os.environ["RETURNOPS_DATABASE_URL"])
    with session_factory() as db:
        # 每次跑用唯一组织名：否则同名组织的 token 串会重复，鉴权可能命中别的行。
        seeded = seed_organization(db, name=f"perf-contract-{uuid.uuid4().hex[:8]}")
        db.commit()
        print(f"ORG_ID={seeded.organization.id}")
        print(f"ORG_TOKEN={seeded.tokens[Role.CUSTOMER_SERVICE][0]}")
    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
