from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from returnops.models import OutboxEvent, utcnow


TOPIC_REFUND_DISPATCH = "refund.dispatch"


def enqueue(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
    topic: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, Any],
) -> OutboxEvent:
    event = OutboxEvent(
        organization_id=organization_id,
        topic=topic,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload_json=payload,
    )
    db.add(event)
    db.flush()
    return event


def claim_batch(db: Session, *, limit: int, lease_seconds: int) -> list[OutboxEvent]:
    now = utcnow()
    stmt = (
        select(OutboxEvent)
        .where(
            OutboxEvent.available_at <= now,
            or_(
                OutboxEvent.status == "pending",
                (OutboxEvent.status == "processing") & (OutboxEvent.lease_until < now),
            ),
        )
        .order_by(OutboxEvent.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    events = list(db.execute(stmt).scalars().all())
    lease_until = now + timedelta(seconds=lease_seconds)
    for event in events:
        event.status = "processing"
        event.lease_until = lease_until
        event.attempts += 1
    db.flush()
    return events


def mark_done(event: OutboxEvent) -> None:
    event.status = "done"
    event.lease_until = None
    event.last_error = None


def reschedule(event: OutboxEvent, *, error: str, delay_seconds: int) -> None:
    event.status = "pending"
    event.lease_until = None
    event.last_error = error[:2000]
    event.available_at = utcnow() + timedelta(seconds=delay_seconds)


def dead_letter(event: OutboxEvent, *, error: str) -> None:
    event.status = "dead"
    event.lease_until = None
    event.last_error = error[:2000]
