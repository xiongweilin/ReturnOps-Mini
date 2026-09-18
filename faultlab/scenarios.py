"""故障实验台场景：在真实网络边界（Toxiproxy）与真实 provider 契约上验证收敛行为。

用法：
    docker compose -f faultlab/docker-compose.faultlab.yml up -d --build
    uv run python faultlab/scenarios.py [--scenario NAME]

每个场景只证明一件事：
    payment-latency  上游慢 2s 仍在 3s 超时预算内成功
    postgres-latency 数据库单次往返 +250ms 时事务边界仍可用、仍只有一个退款意图
    ack-lost         上游已执行但 ACK 被扣住：本地停在 UNKNOWN，靠对账收敛，且只有一次退款
    reset-request    请求根本没到达上游：权威确认"不存在"后允许安全重试
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault(
    "RETURNOPS_DATABASE_URL",
    "postgresql+psycopg://returnops:returnops@127.0.0.1:5432/returnops",
)
os.environ.setdefault("RETURNOPS_PAYMENT_BASE_URL", "http://127.0.0.1:8090")
os.environ.setdefault("RETURNOPS_PAYMENT_WEBHOOK_SECRET", "dev-webhook-secret")

from sqlalchemy import create_engine, select, text  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from returnops.config import get_settings  # noqa: E402
from returnops.domain.states import RefundAttemptStatus, ReturnStatus, Role  # noqa: E402
from returnops.models import Base, RefundAttempt, ReturnCase  # noqa: E402
from returnops.services.outbox import claim_batch  # noqa: E402
from returnops.services.payments import PaymentProviderClient  # noqa: E402
from returnops.services.reconciliation import reconcile_unknown_refund  # noqa: E402
from returnops.services.worker import process_event  # noqa: E402
from tests.conftest import seed_organization  # noqa: E402
from tests.helpers import create_pending_refund  # noqa: E402

TOXIPROXY_ADMIN = os.environ.get("TOXIPROXY_ADMIN", "http://127.0.0.1:8474")
PAYMENT_DIRECT = os.environ.get("PAYMENT_DIRECT", "http://127.0.0.1:8091")
PAYMENT_PROXY = os.environ.get("RETURNOPS_PAYMENT_BASE_URL", "http://127.0.0.1:8090")
POSTGRES_PROXY_URL = os.environ.get(
    "FAULTLAB_POSTGRES_PROXY_URL",
    "postgresql+psycopg://returnops:returnops@127.0.0.1:5433/returnops",
)
CLIENT_TIMEOUT_SECONDS = 3.0  # 与 PaymentProviderClient 的 httpx timeout 保持一致


def _json_request(method: str, url: str, payload: dict | None = None, *, timeout: float = 15.0):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        body = response.read().decode()
    return json.loads(body) if body else None


def clear_toxics(proxy: str) -> None:
    for toxic in _json_request("GET", f"{TOXIPROXY_ADMIN}/proxies/{proxy}/toxics"):
        _json_request("DELETE", f"{TOXIPROXY_ADMIN}/proxies/{proxy}/toxics/{toxic['name']}")


def add_toxic(
    proxy: str, *, name: str, kind: str, stream: str, attributes: dict | None = None
) -> None:
    _json_request(
        "POST",
        f"{TOXIPROXY_ADMIN}/proxies/{proxy}/toxics",
        {
            "name": name,
            "type": kind,
            "stream": stream,
            "toxicity": 1.0,
            "attributes": attributes or {},
        },
    )


def provider_refund(key: str) -> dict | None:
    query = urllib.parse.urlencode({"key": key})
    try:
        return _json_request("GET", f"{PAYMENT_DIRECT}/refunds/by-idempotency-key?{query}")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def set_simulation_mode(mode: str) -> None:
    """切换 provider 契约模拟模式：设置被缓存，必须显式失效。"""
    os.environ["RETURNOPS_PAYMENT_SIMULATION_MODE"] = mode
    get_settings.cache_clear()


def make_session(url: str):
    engine = create_engine(url, pool_pre_ping=True, future=True)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def reset_database(session_factory) -> None:
    """每个场景从干净状态开始：否则 outbox 里上一个场景的事件会先被 claim。"""
    with session_factory() as db:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(text(f'TRUNCATE TABLE "{table.name}" RESTART IDENTITY CASCADE'))
        db.commit()


def attempt_row(db: Session, case_id) -> RefundAttempt:
    return db.execute(
        select(RefundAttempt).where(RefundAttempt.return_case_id == case_id)
    ).scalar_one()


def dispatch_for_case(db: Session, provider: PaymentProviderClient, attempt_id) -> None:
    events = claim_batch(db, limit=5, lease_seconds=30)
    db.commit()
    mine = [
        event
        for event in events
        if (event.payload_json or {}).get("refund_attempt_id") == str(attempt_id)
    ]
    assert len(mine) == 1, f"expected exactly one outbox event for this attempt, got {len(mine)}"
    process_event(db, mine[0], provider=provider)
    db.commit()


def prepare_case(db: Session, label: str) -> tuple[object, ReturnCase, RefundAttempt]:
    seeded = seed_organization(db, name=f"faultlab-{label}")
    case = create_pending_refund(db, seeded)
    db.commit()
    return seeded, case, attempt_row(db, case.id)


def scenario_payment_latency(session_factory, provider) -> None:
    reset_database(session_factory)
    set_simulation_mode("normal")
    clear_toxics("payment")
    try:
        add_toxic(
            "payment",
            name="latency",
            kind="latency",
            stream="upstream",
            attributes={"latency": 2000},
        )
        with session_factory() as db:
            _, case, attempt = prepare_case(db, "latency")
            started = time.monotonic()
            dispatch_for_case(db, provider, attempt.id)
            elapsed = time.monotonic() - started
            status = db.get(ReturnCase, case.id).status
            attempt_status = attempt_row(db, case.id).status
        row = provider_refund(attempt.provider_idempotency_key)
        assert status is ReturnStatus.REFUNDED, (
            f"2s latency must stay inside the budget, got {status}"
        )
        assert attempt_status is RefundAttemptStatus.SUCCEEDED, attempt_status
        assert row is not None
        print(
            f"    上游 +2000ms → {status.value} in {elapsed:.2f}s（预算 {CLIENT_TIMEOUT_SECONDS}s）"
        )
    finally:
        clear_toxics("payment")


def scenario_postgres_latency(session_factory, provider) -> None:
    reset_database(session_factory)
    set_simulation_mode("normal")
    clear_toxics("postgres")
    slow_engine = None
    try:
        add_toxic(
            "postgres",
            name="db-latency",
            kind="latency",
            stream="upstream",
            attributes={"latency": 250},
        )
        slow_engine, slow_factory = make_session(POSTGRES_PROXY_URL)
        with slow_factory() as db:
            started = time.monotonic()
            _, case, _ = prepare_case(db, "dblatency")
            elapsed = time.monotonic() - started
            status = db.get(ReturnCase, case.id).status
            attempts = (
                db.execute(select(RefundAttempt).where(RefundAttempt.return_case_id == case.id))
                .scalars()
                .all()
            )
        assert status is ReturnStatus.REFUND_PENDING, status
        assert len(attempts) == 1, len(attempts)
        print(f"    数据库单次往返 +250ms → 全流程仍完成（{elapsed:.2f}s），只有一个退款意图")
    finally:
        clear_toxics("postgres")
        if slow_engine is not None:
            slow_engine.dispose()


def scenario_ack_lost(session_factory, provider) -> None:
    reset_database(session_factory)
    clear_toxics("payment")
    try:
        # provider 契约：先持久化成功，再扣住 ACK 直到调用方超时。
        set_simulation_mode("timeout_after_processing")
        with session_factory() as db:
            seeded, case, attempt = prepare_case(db, "ack")
            dispatch_for_case(db, provider, attempt.id)
            assert db.get(ReturnCase, case.id).status is ReturnStatus.REFUND_UNKNOWN
            assert attempt_row(db, case.id).status is RefundAttemptStatus.UNKNOWN

            set_simulation_mode("normal")
            finance = seeded.contexts[Role.FINANCE][0]
            outcome = reconcile_unknown_refund(
                db, context=finance, case_id=case.id, provider=provider
            )
            db.commit()
            converged = db.get(ReturnCase, case.id)
            converged_attempt = attempt_row(db, case.id)
        row = provider_refund(attempt.provider_idempotency_key)
        assert row is not None, "provider persisted success before the ACK was withheld"
        assert row["status"] == "succeeded", row
        assert converged.status is ReturnStatus.REFUNDED, converged.status
        assert converged_attempt.status is RefundAttemptStatus.SUCCEEDED, converged_attempt.status
        print(f"    ACK 被扣住 → UNKNOWN → 对账收敛（{outcome.get('resolution')}），只有一次退款")
    finally:
        clear_toxics("payment")
        set_simulation_mode("normal")


def dispatch_when_ready(
    db: Session, provider: PaymentProviderClient, attempt_id, *, timeout_seconds: float = 25.0
) -> None:
    """等待被退避重排的 outbox 事件可以再次被 claim，然后派发一次。"""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        events = claim_batch(db, limit=5, lease_seconds=30)
        db.commit()
        mine = [
            event
            for event in events
            if (event.payload_json or {}).get("refund_attempt_id") == str(attempt_id)
        ]
        if mine:
            process_event(db, mine[0], provider=provider)
            db.commit()
            return
        time.sleep(1.0)
    raise AssertionError("outbox event never became claimable again")


def scenario_reset_request(session_factory, provider) -> None:
    reset_database(session_factory)
    set_simulation_mode("normal")
    clear_toxics("payment")
    try:
        # 连接在请求到达上游之前被重置：provider 侧没有任何记录，本地只能看到一次
        # 可安全重试的失败（provider 503 契约），而不是"未知"。
        add_toxic(
            "payment",
            name="reset",
            kind="reset_peer",
            stream="upstream",
            attributes={"timeout": 0},
        )
        with session_factory() as db:
            _, case, attempt = prepare_case(db, "reset")
            dispatch_for_case(db, provider, attempt.id)
            failed_attempt = attempt_row(db, case.id)
            failed_case = db.get(ReturnCase, case.id)
            assert failed_attempt.status is RefundAttemptStatus.FAILED, failed_attempt.status
            assert failed_case.status is ReturnStatus.REFUND_PENDING, failed_case.status
            assert provider_refund(attempt.provider_idempotency_key) is None, (
                "a request that never reached the provider must not appear there"
            )

            clear_toxics("payment")
            dispatch_when_ready(db, provider, attempt.id)
            final = db.get(ReturnCase, case.id)
            final_attempt = attempt_row(db, case.id)
        row = provider_refund(attempt.provider_idempotency_key)
        assert row is not None
        assert final.status is ReturnStatus.REFUNDED, final.status
        assert final_attempt.status is RefundAttemptStatus.SUCCEEDED, final_attempt.status
        print(
            f"    连接重置（请求未到达）→ 可重试失败 → 重试后 {final.status.value}，仍只有一个退款意图"
        )
    finally:
        clear_toxics("payment")


SCENARIOS = {
    "ack-lost": (scenario_ack_lost, "上游已执行但 ACK 被扣住：停在未知，靠对账收敛"),
    "payment-latency": (scenario_payment_latency, "上游慢 2s 仍在超时预算内成功"),
    "postgres-latency": (scenario_postgres_latency, "数据库变慢时事务边界仍可用"),
    "reset-request": (scenario_reset_request, "请求未到达：权威确认后安全重试"),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), action="append")
    args = parser.parse_args()

    engine, session_factory = make_session(os.environ["RETURNOPS_DATABASE_URL"])
    provider = PaymentProviderClient(base_url=PAYMENT_PROXY)
    failures: list[str] = []
    selected = args.scenario or sorted(SCENARIOS)

    try:
        for name in selected:
            run, description = SCENARIOS[name]
            print(f"== {name}: {description}")
            try:
                run(session_factory, provider)
            except AssertionError as exc:
                failures.append(name)
                print(f"    FAILED: {exc}")
    finally:
        set_simulation_mode("normal")
        for proxy in ("payment", "postgres"):
            try:
                clear_toxics(proxy)
            except Exception as exc:  # noqa: BLE001
                print(f"    cleanup warning ({proxy}): {exc}")
        engine.dispose()

    if failures:
        print(f"fault lab failed: {', '.join(failures)}")
        return 1
    print("fault lab passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
