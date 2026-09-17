from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from returnops.errors import Conflict, NotFound
from returnops.models import RefundAttempt, WebhookReceipt
from returnops.services.payments import mark_success


def _payload_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def process_payment_webhook(db: Session, *, payload: dict[str, Any]) -> dict[str, Any]:
    event_id = str(payload.get("event_id") or "")
    if not event_id:
        raise Conflict("payment webhook missing event_id")
    digest = _payload_hash(payload)

    existing = db.execute(
        select(WebhookReceipt).where(
            WebhookReceipt.provider == "fake-payment",
            WebhookReceipt.event_id == event_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.payload_hash != digest:
            raise Conflict("provider reused webhook event id with a different payload")
        return {"accepted": True, "replayed": True}

    receipt = WebhookReceipt(
        provider="fake-payment",
        event_id=event_id,
        payload_hash=digest,
        payload_json=payload,
    )
    try:
        with db.begin_nested():
            db.add(receipt)
            db.flush()
    except IntegrityError:
        db.expire_all()
        existing = db.execute(
            select(WebhookReceipt).where(
                WebhookReceipt.provider == "fake-payment",
                WebhookReceipt.event_id == event_id,
            )
        ).scalar_one_or_none()
        if existing is None:
            raise Conflict("webhook deduplication race could not be resolved") from None
        if existing.payload_hash != digest:
            raise Conflict("provider reused webhook event id with a different payload") from None
        return {"accepted": True, "replayed": True}

    key = str(payload.get("idempotency_key") or "")
    attempt = db.execute(
        select(RefundAttempt).where(RefundAttempt.provider_idempotency_key == key)
    ).scalar_one_or_none()
    if attempt is None:
        raise NotFound("no refund attempt matches webhook idempotency key")

    status = str(payload.get("status") or "")
    if status == "succeeded":
        provider_ref = str(payload.get("refund_id") or "")
        if not provider_ref:
            raise Conflict("successful webhook missing refund_id")
        # Always validate success evidence, even when the attempt was already
        # confirmed. A later event with a different refund reference or amount
        # is a provider inconsistency, not a harmless duplicate.
        mark_success(
            db,
            attempt,
            provider_ref=provider_ref,
            evidence=payload,
            evidence_source="webhook",
        )
    return {"accepted": True, "replayed": False}
