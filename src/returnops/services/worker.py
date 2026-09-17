from __future__ import annotations

import logging
import time
import uuid

import httpx
from sqlalchemy.orm import Session

from returnops.config import get_settings
from returnops.db import SessionLocal
from returnops.errors import ExternalSystemFailure
from returnops.services.outbox import (
    TOPIC_REFUND_DISPATCH,
    claim_batch,
    dead_letter,
    mark_done,
    reschedule,
)
from returnops.services.payments import (
    PaymentProviderClient,
    get_refund_attempt,
    mark_dispatching,
    mark_known_failure,
    mark_manual_reconciliation_needed,
    mark_success,
    mark_unknown,
)

logger = logging.getLogger("returnops.worker")


def _backoff(attempts: int) -> int:
    return min(60, 2 ** max(0, attempts - 1))


def process_event(db: Session, event, *, provider: PaymentProviderClient) -> None:
    settings = get_settings()
    if event.topic != TOPIC_REFUND_DISPATCH:
        dead_letter(event, error=f"unknown topic: {event.topic}")
        return

    attempt_id = uuid.UUID(str(event.payload_json["refund_attempt_id"]))
    attempt = get_refund_attempt(db, attempt_id)
    if attempt.status.value == "succeeded":
        mark_done(event)
        return
    if attempt.status.value == "unknown":
        # This is the central safety rule: an ambiguous external result is not retried.
        mark_done(event)
        return

    mark_dispatching(db, attempt)
    db.commit()  # Persist "we attempted" before crossing the network boundary.

    try:
        result = provider.create_refund(
            idempotency_key=attempt.provider_idempotency_key,
            amount_minor=attempt.amount_minor,
            currency=attempt.currency,
            return_case_id=attempt.return_case_id,
        )
    except ExternalSystemFailure as exc:
        # Fake provider's 503 contract means the request was rejected before processing.
        # This is explicitly safe to retry. Real integrations must earn this assumption
        # from their provider contract instead of copying it blindly.
        db.refresh(event)
        db.refresh(attempt)
        mark_known_failure(db, attempt, error=str(exc))
        if event.attempts >= settings.max_dispatch_attempts:
            mark_manual_reconciliation_needed(
                db, attempt, reason="safe retries exhausted after known provider failures"
            )
            dead_letter(event, error=str(exc))
        else:
            reschedule(event, error=str(exc), delay_seconds=_backoff(event.attempts))
        return
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        # Once bytes may have crossed the network, absence of an ACK does not prove
        # failure. Record UNKNOWN and stop automatic retries.
        db.refresh(event)
        db.refresh(attempt)
        # A webhook may have committed provider success while this HTTP request was
        # still waiting for an ACK. Fresh database evidence wins over the local
        # timeout; never downgrade SUCCEEDED back to UNKNOWN.
        if attempt.status.value != "succeeded":
            mark_unknown(db, attempt, error=f"{type(exc).__name__}: {exc}")
        mark_done(event)
        return
    except Exception as exc:
        db.refresh(event)
        db.refresh(attempt)
        if attempt.status.value != "succeeded":
            mark_unknown(db, attempt, error=f"unexpected provider ambiguity: {exc}")
        mark_done(event)
        return

    db.refresh(event)
    db.refresh(attempt)
    mark_success(
        db,
        attempt,
        provider_ref=result.provider_ref,
        evidence=result.raw,
        evidence_source="synchronous_provider_response",
    )
    mark_done(event)


def run_once(*, provider: PaymentProviderClient | None = None, limit: int = 10) -> int:
    provider = provider or PaymentProviderClient()
    settings = get_settings()
    with SessionLocal() as db:
        events = claim_batch(db, limit=limit, lease_seconds=settings.worker_lease_seconds)
        db.commit()
    processed = 0
    for claimed in events:
        with SessionLocal() as db:
            event = db.get(type(claimed), claimed.id)
            if event is None or event.status != "processing":
                continue
            try:
                process_event(db, event, provider=provider)
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("event processing failed", extra={"event_id": str(claimed.id)})
            processed += 1
    return processed


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    while True:
        count = run_once()
        if count == 0:
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
