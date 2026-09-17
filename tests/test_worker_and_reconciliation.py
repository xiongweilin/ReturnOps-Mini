from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from returnops.domain.states import RefundAttemptStatus, ReturnStatus, Role
from returnops.models import OutboxEvent, RefundAttempt, ReturnCase
from returnops.services.outbox import claim_batch
from returnops.services.payments import PaymentProviderClient, mark_success
from returnops.services.reconciliation import reconcile_unknown_refund
from returnops.services.returns import retry_failed_refund
from returnops.services.worker import process_event
from tests.helpers import create_pending_refund


def _claim_one(db):
    events = claim_batch(db, limit=1, lease_seconds=30)
    assert len(events) == 1
    db.commit()
    return events[0]


def test_successful_dispatch_moves_case_to_refunded(db, seeded) -> None:
    case = create_pending_refund(db, seeded)
    db.commit()
    event = _claim_one(db)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "refund_id": "rf_ok",
                "status": "succeeded",
                "amount_minor": 1000,
                "currency": "USD",
                "idempotency_key": request.headers["Idempotency-Key"],
            },
        )

    process_event(db, event, provider=PaymentProviderClient(transport=httpx.MockTransport(handler)))
    db.commit()
    refreshed = db.get(ReturnCase, case.id)
    attempt = db.execute(select(RefundAttempt).where(RefundAttempt.return_case_id == case.id)).scalar_one()
    assert refreshed.status is ReturnStatus.REFUNDED
    assert attempt.status is RefundAttemptStatus.SUCCEEDED
    assert attempt.provider_ref == "rf_ok"


def test_network_timeout_becomes_unknown_and_is_not_rescheduled(db, seeded) -> None:
    case = create_pending_refund(db, seeded)
    db.commit()
    event = _claim_one(db)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("ACK lost after request may have been processed", request=request)

    process_event(db, event, provider=PaymentProviderClient(transport=httpx.MockTransport(handler)))
    db.commit()
    refreshed = db.get(ReturnCase, case.id)
    attempt = db.execute(select(RefundAttempt).where(RefundAttempt.return_case_id == case.id)).scalar_one()
    outbox = db.get(OutboxEvent, event.id)
    assert refreshed.status is ReturnStatus.REFUND_UNKNOWN
    assert attempt.status is RefundAttemptStatus.UNKNOWN
    assert outbox.status == "done"


def test_webhook_success_is_not_downgraded_when_http_ack_times_out(db, seeded) -> None:
    case = create_pending_refund(db, seeded)
    db.commit()
    event = _claim_one(db)

    def handler(request: httpx.Request) -> httpx.Response:
        attempt = db.execute(
            select(RefundAttempt).where(RefundAttempt.return_case_id == case.id)
        ).scalar_one()
        mark_success(
            db,
            attempt,
            provider_ref="rf_webhook_won",
            evidence={"source": "simulated_webhook"},
            evidence_source="webhook",
        )
        db.commit()
        raise httpx.ReadTimeout("ACK lost after webhook committed success", request=request)

    process_event(db, event, provider=PaymentProviderClient(transport=httpx.MockTransport(handler)))
    db.commit()

    refreshed = db.get(ReturnCase, case.id)
    attempt = db.execute(
        select(RefundAttempt).where(RefundAttempt.return_case_id == case.id)
    ).scalar_one()
    outbox = db.get(OutboxEvent, event.id)
    assert refreshed.status is ReturnStatus.REFUNDED
    assert attempt.status is RefundAttemptStatus.SUCCEEDED
    assert attempt.provider_ref == "rf_webhook_won"
    assert outbox.status == "done"


def test_safe_retry_exhaustion_routes_to_manual_reconciliation(db, seeded, monkeypatch) -> None:
    case = create_pending_refund(db, seeded)
    db.commit()
    event = _claim_one(db)
    event.attempts = 3
    db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "rejected before processing"})

    process_event(db, event, provider=PaymentProviderClient(transport=httpx.MockTransport(handler)))
    db.commit()
    refreshed = db.get(ReturnCase, case.id)
    attempt = db.execute(select(RefundAttempt).where(RefundAttempt.return_case_id == case.id)).scalar_one()
    outbox = db.get(OutboxEvent, event.id)
    assert refreshed.status is ReturnStatus.NEEDS_RECONCILIATION
    assert attempt.status is RefundAttemptStatus.FAILED
    assert outbox.status == "dead"


def test_unknown_requires_authoritative_lookup_before_retry(db, seeded) -> None:
    case = create_pending_refund(db, seeded)
    db.commit()
    event = _claim_one(db)

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("unknown", request=request)

    process_event(
        db,
        event,
        provider=PaymentProviderClient(transport=httpx.MockTransport(timeout_handler)),
    )
    db.commit()
    case = db.get(ReturnCase, case.id)
    finance = seeded.contexts[Role.FINANCE][0]

    def absent_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "not found"})

    outcome = reconcile_unknown_refund(
        db,
        context=finance,
        case_id=case.id,
        provider=PaymentProviderClient(transport=httpx.MockTransport(absent_handler)),
    )
    assert outcome["resolution"] == "provider_confirmed_absent"
    db.flush()
    case = db.get(ReturnCase, case.id)
    attempt = db.execute(select(RefundAttempt).where(RefundAttempt.return_case_id == case.id)).scalar_one()
    assert case.status is ReturnStatus.NEEDS_RECONCILIATION
    assert attempt.status is RefundAttemptStatus.FAILED

    retried = retry_failed_refund(
        db,
        context=finance,
        case_id=case.id,
        expected_version=case.version,
    )
    assert retried.status is ReturnStatus.REFUND_PENDING
    assert attempt.status is RefundAttemptStatus.PLANNED


def test_expired_dispatching_attempt_can_be_recovered_with_same_provider_key(db, seeded) -> None:
    """A worker crash after persisting DISPATCHING must not strand the refund forever."""
    case = create_pending_refund(db, seeded)
    db.commit()
    event = _claim_one(db)
    attempt = db.execute(
        select(RefundAttempt).where(RefundAttempt.return_case_id == case.id)
    ).scalar_one()

    # Simulate the first worker crossing the durable boundary and then dying
    # before it can persist a provider result.
    attempt.status = RefundAttemptStatus.DISPATCHING
    attempt.dispatch_count = 1
    db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "refund_id": "rf_recovered",
                "status": "succeeded",
                "amount_minor": attempt.amount_minor,
                "currency": attempt.currency,
                "idempotency_key": request.headers["Idempotency-Key"],
            },
        )

    process_event(db, event, provider=PaymentProviderClient(transport=httpx.MockTransport(handler)))
    db.commit()
    db.refresh(attempt)
    assert attempt.status is RefundAttemptStatus.SUCCEEDED
    assert attempt.provider_ref == "rf_recovered"
    assert attempt.dispatch_count == 2
    assert db.get(ReturnCase, case.id).status is ReturnStatus.REFUNDED


def test_provider_success_evidence_must_match_refund_intent(db, seeded) -> None:
    case = create_pending_refund(db, seeded)
    attempt = db.execute(
        select(RefundAttempt).where(RefundAttempt.return_case_id == case.id)
    ).scalar_one()

    from returnops.errors import Conflict

    with pytest.raises(Conflict, match="amount"):
        mark_success(
            db,
            attempt,
            provider_ref="rf_wrong_amount",
            evidence={"amount_minor": attempt.amount_minor + 1, "currency": attempt.currency},
            evidence_source="test",
        )


def test_reconciliation_does_not_treat_non_success_provider_row_as_absent(db, seeded) -> None:
    case = create_pending_refund(db, seeded)
    db.commit()
    event = _claim_one(db)

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("unknown", request=request)

    process_event(
        db,
        event,
        provider=PaymentProviderClient(transport=httpx.MockTransport(timeout_handler)),
    )
    db.commit()
    finance = seeded.contexts[Role.FINANCE][0]

    def pending_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "refund_id": "rf_pending",
                "status": "pending",
                "amount_minor": 1000,
                "currency": "USD",
                "idempotency_key": request.url.params["key"],
            },
        )

    outcome = reconcile_unknown_refund(
        db,
        context=finance,
        case_id=case.id,
        provider=PaymentProviderClient(transport=httpx.MockTransport(pending_handler)),
    )
    db.flush()
    attempt = db.execute(
        select(RefundAttempt).where(RefundAttempt.return_case_id == case.id)
    ).scalar_one()
    assert outcome["resolution"] == "provider_non_terminal_or_unrecognized"
    assert attempt.status is RefundAttemptStatus.UNKNOWN
    assert db.get(ReturnCase, case.id).status is ReturnStatus.NEEDS_RECONCILIATION


def test_conflicting_provider_success_is_dead_lettered_for_manual_reconciliation(db, seeded) -> None:
    case = create_pending_refund(db, seeded)
    db.commit()
    event = _claim_one(db)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "refund_id": "rf_wrong",
                "status": "succeeded",
                "amount_minor": 999999,
                "currency": "USD",
                "idempotency_key": request.headers["Idempotency-Key"],
            },
        )

    process_event(db, event, provider=PaymentProviderClient(transport=httpx.MockTransport(handler)))
    db.commit()
    attempt = db.execute(
        select(RefundAttempt).where(RefundAttempt.return_case_id == case.id)
    ).scalar_one()
    outbox = db.get(OutboxEvent, event.id)
    assert attempt.status is RefundAttemptStatus.UNKNOWN
    assert db.get(ReturnCase, case.id).status is ReturnStatus.NEEDS_RECONCILIATION
    assert outbox.status == "dead"
