from __future__ import annotations

import pytest
from sqlalchemy import select

from returnops.domain.states import RefundAttemptStatus, ReturnStatus
from returnops.errors import Conflict
from returnops.models import RefundAttempt, ReturnCase, WebhookReceipt
from returnops.services.webhooks import process_payment_webhook
from .helpers import create_pending_refund


def test_success_webhook_is_deduplicated(db, seeded) -> None:
    case = create_pending_refund(db, seeded)
    attempt = db.execute(
        select(RefundAttempt).where(RefundAttempt.return_case_id == case.id)
    ).scalar_one()
    payload = {
        "event_id": "evt-1",
        "refund_id": "rf-webhook",
        "idempotency_key": attempt.provider_idempotency_key,
        "status": "succeeded",
        "amount_minor": attempt.amount_minor,
        "currency": attempt.currency,
    }
    first = process_payment_webhook(db, payload=payload)
    second = process_payment_webhook(db, payload=payload)
    assert first == {"accepted": True, "replayed": False}
    assert second == {"accepted": True, "replayed": True}
    assert db.query(WebhookReceipt).count() == 1
    assert db.get(ReturnCase, case.id).status is ReturnStatus.REFUNDED
    assert attempt.status is RefundAttemptStatus.SUCCEEDED


def test_reused_event_id_with_changed_body_is_rejected(db, seeded) -> None:
    case = create_pending_refund(db, seeded)
    attempt = db.execute(
        select(RefundAttempt).where(RefundAttempt.return_case_id == case.id)
    ).scalar_one()
    payload = {
        "event_id": "evt-conflict",
        "refund_id": "rf-a",
        "idempotency_key": attempt.provider_idempotency_key,
        "status": "succeeded",
    }
    process_payment_webhook(db, payload=payload)
    with pytest.raises(Conflict):
        process_payment_webhook(db, payload={**payload, "refund_id": "rf-b"})


def test_new_webhook_event_cannot_change_confirmed_provider_reference(db, seeded) -> None:
    case = create_pending_refund(db, seeded)
    attempt = db.execute(
        select(RefundAttempt).where(RefundAttempt.return_case_id == case.id)
    ).scalar_one()
    first = {
        "event_id": "evt-first-reference",
        "refund_id": "rf-stable",
        "idempotency_key": attempt.provider_idempotency_key,
        "status": "succeeded",
        "amount_minor": attempt.amount_minor,
        "currency": attempt.currency,
    }
    process_payment_webhook(db, payload=first)

    with pytest.raises(Conflict, match="conflicting refund references"):
        process_payment_webhook(
            db,
            payload={**first, "event_id": "evt-second-reference", "refund_id": "rf-impossible"},
        )
