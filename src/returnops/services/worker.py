from __future__ import annotations

import logging
import time
import uuid

import httpx
from sqlalchemy.orm import Session

from returnops.config import get_settings
from returnops.db import SessionLocal
from returnops.errors import Conflict, ExternalSystemFailure
from returnops.models import OutboxEvent
from returnops.services.outbox import (
    TOPIC_REFUND_DISPATCH,
    claim_batch,
    claim_event,
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
        # 核心安全规则：ambiguous external result 不能自动重试。
        mark_done(event)
        return

    mark_dispatching(db, attempt)
    db.commit()  # 在跨越网络边界前先持久化“已经尝试过”。

    try:
        result = provider.create_refund(
            idempotency_key=attempt.provider_idempotency_key,
            amount_minor=attempt.amount_minor,
            currency=attempt.currency,
            return_case_id=attempt.return_case_id,
        )
    except ExternalSystemFailure as exc:
        # 模拟 provider 的 503 contract 表示请求在处理前已被拒绝。
        # 这里明确允许安全重试。真实 integration 必须从其 provider contract
        # 中证明这一前提，而不能直接照搬。
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
        # 一旦字节可能已经跨过网络边界，缺少 ACK 并不能证明
        # 失败。必须记录 UNKNOWN，并停止自动重试。
        db.refresh(event)
        db.refresh(attempt)
        # 在这个 HTTP request 仍等待 ACK 时，webhook 可能已经提交
        # provider success。更新的数据库 evidence 优先于本地
        # timeout；绝不能把 SUCCEEDED 降级回 UNKNOWN。
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
    try:
        mark_success(
            db,
            attempt,
            provider_ref=result.provider_ref,
            evidence=result.raw,
            evidence_source="synchronous_provider_response",
        )
    except Conflict as exc:
        # Provider 声称成功，但 evidence 与 durable
        # local intent 冲突（例如 amount/currency/reference 不一致）。这既
        # 不是安全重试，也不是成功：保持 ambiguity，并停止
        # 自动 dispatch，直到人工/provider 调查解决。
        mark_unknown(db, attempt, error=f"provider evidence conflict: {exc}")
        mark_manual_reconciliation_needed(
            db,
            attempt,
            reason=f"provider success evidence conflicts with refund intent: {exc}",
        )
        dead_letter(event, error=str(exc))
        return
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


def process_event_once(event_id: uuid.UUID, *, provider: PaymentProviderClient) -> bool:
    settings = get_settings()
    with SessionLocal() as db:
        event = claim_event(db, event_id=event_id, lease_seconds=settings.worker_lease_seconds)
        if event is None:
            return False
        claimed_id = event.id
        db.commit()

    with SessionLocal() as db:
        event = db.get(OutboxEvent, claimed_id)
        if event is None or event.status != "processing":
            return False
        process_event(db, event, provider=provider)
        db.commit()
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    while True:
        count = run_once()
        if count == 0:
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
