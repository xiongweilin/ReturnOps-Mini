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
        # 已提交的记录绝不会被有意留在不完整状态，因此该状态
        # 表示数据损坏或存在不受支持的外部写入方，而不是一个
        # 调用方可以静默重放的请求。
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

    # savepoint 很重要。在 PostgreSQL 中，对唯一约束
    # (org, scope, key) 的并发插入会在这里串行化。失败方会等待成功方
    # 的事务并收到 IntegrityError。只回滚 savepoint
    # 可以让请求事务继续可用，使失败方读取并重放
    # 成功方已提交的响应，而不是向外泄漏 500。
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
