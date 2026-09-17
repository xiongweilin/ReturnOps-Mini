from __future__ import annotations

import threading
import uuid

import pytest
from sqlalchemy import func, select

from returnops.domain.states import ReturnStatus, Role
from returnops.errors import IdempotencyConflict, VersionConflict
from returnops.models import Approval, Membership, Organization, ReturnCase, User
from returnops.security import hash_token
from returnops.services.idempotency import claim, complete
from returnops.services.returns import approve_refund
from returnops.services.tenancy import TenantContext

pytestmark = pytest.mark.integration

def test_twenty_concurrent_same_key_requests_replay_one_response(pg_factory) -> None:
    with pg_factory() as db:
        org = Organization(name="Concurrency")
        db.add(org)
        db.commit()
        org_id = org.id

    barrier = threading.Barrier(20)
    results: list[str] = []
    errors: list[str] = []
    lock = threading.Lock()

    def worker(index: int) -> None:
        with pg_factory() as db:
            try:
                barrier.wait(timeout=15)
                claimed = claim(
                    db,
                    organization_id=org_id,
                    scope="concurrency",
                    key="same-key",
                    request_payload={"same": True},
                )
                if claimed.replay is not None:
                    result = claimed.replay
                else:
                    result = {"winner": str(index)}
                    complete(claimed, result)
                db.commit()
                with lock:
                    results.append(result["winner"])
            except Exception as exc:  # pragma: no cover - diagnostic path
                db.rollback()
                with lock:
                    errors.append(type(exc).__name__)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert errors == []
    assert len(results) == 20
    assert len(set(results)) == 1


def test_two_concurrent_finance_approvals_have_one_cas_winner(pg_factory) -> None:
    with pg_factory() as db:
        org = Organization(name="CAS")
        service = User(email="service@cas.test", display_name="service", api_token_hash=hash_token("s"))
        fa = User(email="fa@cas.test", display_name="fa", api_token_hash=hash_token("fa"))
        fb = User(email="fb@cas.test", display_name="fb", api_token_hash=hash_token("fb"))
        db.add_all([org, service, fa, fb])
        db.flush()
        db.add_all(
            [
                Membership(organization_id=org.id, user_id=service.id, role=Role.CUSTOMER_SERVICE),
                Membership(organization_id=org.id, user_id=fa.id, role=Role.FINANCE),
                Membership(organization_id=org.id, user_id=fb.id, role=Role.FINANCE),
            ]
        )
        case = ReturnCase(
            organization_id=org.id,
            case_ref="RET-CAS",
            external_order_ref="ORDER",
            customer_ref="C",
            reason="broken",
            requested_amount_minor=1000,
            currency="USD",
            status=ReturnStatus.INSPECTED,
            version=4,
            created_by_user_id=service.id,
        )
        db.add(case)
        db.commit()
        org_id, case_id, fa_id, fb_id = org.id, case.id, fa.id, fb.id

    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def approve(user_id: uuid.UUID) -> None:
        with pg_factory() as db:
            try:
                barrier.wait(timeout=10)
                approve_refund(
                    db,
                    context=TenantContext(org_id, user_id, Role.FINANCE),
                    case_id=case_id,
                    expected_version=4,
                    approved_amount_minor=1000,
                    rationale="concurrent",
                )
                db.commit()
                outcome = "ok"
            except VersionConflict:
                db.rollback()
                outcome = "version_conflict"
            with lock:
                outcomes.append(outcome)

    a = threading.Thread(target=approve, args=(fa_id,))
    b = threading.Thread(target=approve, args=(fb_id,))
    a.start()
    b.start()
    a.join(timeout=20)
    b.join(timeout=20)
    assert sorted(outcomes) == ["ok", "version_conflict"]


def test_concurrent_high_value_first_approval_has_one_first_approver(pg_factory) -> None:
    with pg_factory() as db:
        org = Organization(name="High value CAS")
        service = User(
            email="service-high@cas.test",
            display_name="service",
            api_token_hash=hash_token("s-high"),
         )
        fa = User(
            email="fa-high@cas.test",
            display_name="fa",
            api_token_hash=hash_token("fa-high"),
        )
        fb = User(
            email="fb-high@cas.test",
            display_name="fb",
            api_token_hash=hash_token("fb-high"),
        )
        db.add_all([org, service, fa, fb])
        db.flush()
        db.add_all(
            [
                Membership(organization_id=org.id, user_id=service.id, role=Role.CUSTOMER_SERVICE),
                Membership(organization_id=org.id, user_id=fa.id, role=Role.FINANCE),
                Membership(organization_id=org.id, user_id=fb.id, role=Role.FINANCE),
            ]
        )
        case = ReturnCase(
            organization_id=org.id,
            case_ref="RET-HIGH-CAS",
            external_order_ref="ORDER-HIGH",
            customer_ref="C",
            reason="broken",
            requested_amount_minor=80_000,
            currency="USD",
            status=ReturnStatus.INSPECTED,
            version=4,
            created_by_user_id=service.id,
        )
        db.add(case)
        db.commit()
        org_id, case_id, fa_id, fb_id = org.id, case.id, fa.id, fb.id

    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def approve(user_id: uuid.UUID) -> None:
        with pg_factory() as db:
            try:
                barrier.wait(timeout=10)
                _case, needs_second = approve_refund(
                    db,
                    context=TenantContext(org_id, user_id, Role.FINANCE),
                    case_id=case_id,
                    expected_version=4,
                    approved_amount_minor=60_000,
                    rationale="concurrent first approval",
                )
                assert needs_second is True
                db.commit()
                outcome = "ok"
            except VersionConflict:
                db.rollback()
                outcome = "version_conflict"
            with lock:
                outcomes.append(outcome)

    a = threading.Thread(target=approve, args=(fa_id,))
    b = threading.Thread(target=approve, args=(fb_id,))
    a.start()
    b.start()
    a.join(timeout=20)
    b.join(timeout=20)

    assert sorted(outcomes) == ["ok", "version_conflict"]
    with pg_factory() as db:
        persisted = db.get(ReturnCase, case_id)
        assert persisted.status is ReturnStatus.INSPECTED
        assert persisted.version == 5
        approval_count = db.execute(
            select(func.count()).select_from(Approval).where(Approval.return_case_id == case_id)
        ).scalar_one()
        assert approval_count == 1


def test_concurrent_same_key_different_body_returns_domain_conflict(pg_factory) -> None:
    with pg_factory() as db:
        org = Organization(name="Idempotency conflict")
        db.add(org)
        db.commit()
        org_id = org.id

    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def worker(value: int) -> None:
        with pg_factory() as db:
            try:
                barrier.wait(timeout=10)
                claimed = claim(
                    db,
                    organization_id=org_id,
                    scope="conflict",
                    key="same-key-different-body",
                    request_payload={"value": value},
                )
                if claimed.replay is None:
                    complete(claimed, {"value": value})
                db.commit()
                outcome = "ok"
            except IdempotencyConflict:
                db.rollback()
                outcome = "idempotency_conflict"
            with lock:
                outcomes.append(outcome)

    a = threading.Thread(target=worker, args=(1,))
    b = threading.Thread(target=worker, args=(2,))
    a.start()
    b.start()
    a.join(timeout=20)
    b.join(timeout=20)
    assert sorted(outcomes) == ["idempotency_conflict", "ok"]


