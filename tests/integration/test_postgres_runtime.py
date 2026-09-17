from __future__ import annotations

import threading
import uuid
from datetime import timedelta

import httpx
import pytest

from returnops.domain.states import RefundAttemptStatus, ReturnStatus
from returnops.models import Organization, OutboxEvent, RefundAttempt, ReturnCase, User, utcnow
from returnops.security import hash_token
from returnops.services.outbox import TOPIC_REFUND_DISPATCH, claim_batch, enqueue
from returnops.services.payments import PaymentProviderClient, mark_success
from returnops.services.webhooks import process_payment_webhook
from returnops.services.worker import process_event

pytestmark = pytest.mark.integration

def test_two_workers_claim_disjoint_outbox_rows(pg_factory) -> None:
    with pg_factory() as db:
        org = Organization(name="Outbox")
        db.add(org)
        db.flush()
        for index in range(12):
            enqueue(
                db,
                organization_id=org.id,
                topic="test.topic",
                aggregate_type="test",
                aggregate_id=str(index),
                payload={"index": index},
            )
        db.commit()

    barrier = threading.Barrier(2)
    claimed_sets: list[set[uuid.UUID]] = []
    lock = threading.Lock()

    def worker() -> None:
        with pg_factory() as db:
            barrier.wait(timeout=10)
            rows = claim_batch(db, limit=10, lease_seconds=60)
            ids = {row.id for row in rows}
            db.commit()
            with lock:
                claimed_sets.append(ids)

    a = threading.Thread(target=worker)
    b = threading.Thread(target=worker)
    a.start()
    b.start()
    a.join(timeout=20)
    b.join(timeout=20)

    assert len(claimed_sets) == 2
    assert claimed_sets[0].isdisjoint(claimed_sets[1])
    assert len(claimed_sets[0] | claimed_sets[1]) == 12


def test_expired_processing_lease_is_reclaimable(pg_factory) -> None:
    with pg_factory() as db:
        org = Organization(name="Lease")
        db.add(org)
        db.flush()
        event = OutboxEvent(
            organization_id=org.id,
            topic="test.topic",
            aggregate_type="test",
            aggregate_id="1",
            payload_json={"x": 1},
            status="processing",
            attempts=1,
            lease_until=utcnow() - timedelta(seconds=1),
        )
        db.add(event)
        db.commit()
        event_id = event.id

    with pg_factory() as db:
        rows = claim_batch(db, limit=10, lease_seconds=60)
        db.commit()
        assert [row.id for row in rows] == [event_id]
        assert rows[0].status == "processing"
        assert rows[0].attempts == 2
        assert rows[0].lease_until is not None


def _seed_pending_refund_for_runtime(pg_factory):
    with pg_factory() as db:
        org = Organization(name=f"Runtime-{uuid.uuid4().hex[:6]}")
        service = User(
            email=f"service-{uuid.uuid4().hex}@runtime.test",
            display_name="service",
            api_token_hash=hash_token(uuid.uuid4().hex),
        )
        db.add_all([org, service])
        db.flush()
        case = ReturnCase(
            organization_id=org.id,
            case_ref=f"RET-{uuid.uuid4().hex[:8]}",
            external_order_ref="ORDER-RUNTIME",
            customer_ref="CUSTOMER",
            reason="broken",
            requested_amount_minor=1000,
            approved_amount_minor=1000,
            currency="USD",
            status=ReturnStatus.REFUND_PENDING,
            version=6,
            created_by_user_id=service.id,
        )
        attempt = RefundAttempt(
            organization_id=org.id,
            return_case_id=case.id,
            provider_idempotency_key=f"return:{case.id}:refund:v1",
            amount_minor=1000,
            currency="USD",
            status=RefundAttemptStatus.PLANNED,
        )
        db.add_all([case, attempt])
        db.flush()
        event = enqueue(
            db,
            organization_id=org.id,
            topic=TOPIC_REFUND_DISPATCH,
            aggregate_type="refund_attempt",
            aggregate_id=str(attempt.id),
            payload={"refund_attempt_id": str(attempt.id)},
        )
        db.commit()
        return case.id, attempt.id, event.id, attempt.provider_idempotency_key


def test_webhook_commit_wins_over_later_http_timeout_across_transactions(pg_factory) -> None:
    case_id, attempt_id, event_id, _ = _seed_pending_refund_for_runtime(pg_factory)

    with pg_factory() as worker_db:
        claimed = claim_batch(worker_db, limit=1, lease_seconds=60)
        assert [row.id for row in claimed] == [event_id]
        worker_db.commit()
        event = worker_db.get(OutboxEvent, event_id)

        def handler(request: httpx.Request) -> httpx.Response:
            # Simulate a webhook handled and committed by another API transaction
            # while the original provider request is still waiting for its ACK.
            with pg_factory() as webhook_db:
                other_attempt = webhook_db.get(RefundAttempt, attempt_id)
                assert other_attempt is not None
                mark_success(
                    webhook_db,
                    other_attempt,
                    provider_ref="rf_webhook_first",
                    evidence={"amount_minor": 1000, "currency": "USD"},
                    evidence_source="webhook",
                )
                webhook_db.commit()
            raise httpx.ReadTimeout("ACK lost after webhook committed", request=request)

        process_event(
            worker_db,
            event,
            provider=PaymentProviderClient(transport=httpx.MockTransport(handler)),
        )
        worker_db.commit()

    with pg_factory() as db:
        attempt = db.get(RefundAttempt, attempt_id)
        case = db.get(ReturnCase, case_id)
        outbox = db.get(OutboxEvent, event_id)
        assert attempt.status is RefundAttemptStatus.SUCCEEDED
        assert attempt.provider_ref == "rf_webhook_first"
        assert case.status is ReturnStatus.REFUNDED
        assert outbox.status == "done"


def test_concurrent_duplicate_webhook_is_processed_once(pg_factory) -> None:
    case_id, attempt_id, _event_id, provider_key = _seed_pending_refund_for_runtime(pg_factory)
    payload = {
        "event_id": "evt-concurrent-same",
        "refund_id": "rf-concurrent",
        "idempotency_key": provider_key,
        "status": "succeeded",
        "amount_minor": 1000,
        "currency": "USD",
    }
    barrier = threading.Barrier(2)
    results: list[dict] = []
    errors: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        with pg_factory() as db:
            try:
                barrier.wait(timeout=10)
                result = process_payment_webhook(db, payload=payload)
                db.commit()
                with lock:
                    results.append(result)
            except Exception as exc:  # pragma: no cover - diagnostics on failure
                db.rollback()
                with lock:
                    errors.append(type(exc).__name__)

    a = threading.Thread(target=worker)
    b = threading.Thread(target=worker)
    a.start()
    b.start()
    a.join(timeout=20)
    b.join(timeout=20)

    assert errors == []
    assert len(results) == 2
    assert sorted(result["replayed"] for result in results) == [False, True]
    with pg_factory() as db:
        assert db.get(RefundAttempt, attempt_id).status is RefundAttemptStatus.SUCCEEDED
        assert db.get(ReturnCase, case_id).status is ReturnStatus.REFUNDED
