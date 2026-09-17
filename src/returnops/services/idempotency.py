from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from returnops.errors import Conflict, IdempotencyConflict, ValidationFailure
from returnops.models import IdempotencyRecord


def canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass
class IdempotencyClaim:
    record: IdempotencyRecord | None
    replay: dict[str, Any] | None


def _validate_existing(
    existing: IdempotencyRecord,
    *,
    request_hash: str,
) -> IdempotencyClaim:
    if existing.request_hash != request_hash:
        raise IdempotencyConflict("idempotency key was already used with a different request")
    if existing.response_json is None:
        # A committed row is never intentionally left incomplete. This state therefore
        # indicates corruption or an unsupported external writer, not a request that
        # callers should silently replay.
        raise Conflict("idempotency record exists without a completed response")
    return IdempotencyClaim(record=None, replay=dict(existing.response_json))


def claim(
    db: Session,
    *,
    organization_id: uuid.UUID,
    scope: str,
    key: str,
    request_payload: Any,
) -> IdempotencyClaim:
    if not key or len(key) > 200:
        raise ValidationFailure("Idempotency-Key must be present and at most 200 characters")

    request_hash = canonical_hash(request_payload)
    existing = db.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.organization_id == organization_id,
            IdempotencyRecord.scope == scope,
            IdempotencyRecord.key == key,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return _validate_existing(existing, request_hash=request_hash)

    record = IdempotencyRecord(
        organization_id=organization_id,
        scope=scope,
        key=key,
        request_hash=request_hash,
        response_json=None,
    )

    # The savepoint is important. On PostgreSQL, concurrent inserts on the unique
    # (org, scope, key) constraint serialize here. The loser waits for the winner's
    # transaction and then receives IntegrityError. Rolling back only the savepoint
    # keeps the request transaction usable so the loser can read and replay the
    # winner's committed response instead of leaking a 500.
    try:
        with db.begin_nested():
            db.add(record)
            db.flush()
    except IntegrityError:
        db.expire_all()
        existing = db.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.organization_id == organization_id,
                IdempotencyRecord.scope == scope,
                IdempotencyRecord.key == key,
            )
        ).scalar_one_or_none()
        if existing is None:
            raise Conflict("idempotency race could not be resolved") from None
        return _validate_existing(existing, request_hash=request_hash)

    return IdempotencyClaim(record=record, replay=None)


def complete(claimed: IdempotencyClaim, response: dict[str, Any]) -> None:
    if claimed.record is None:
        raise RuntimeError("cannot complete a replayed idempotency claim")
    claimed.record.response_json = response
