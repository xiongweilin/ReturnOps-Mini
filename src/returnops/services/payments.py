from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from returnops.config import get_settings
from returnops.domain.states import RefundAttemptStatus, ReturnStatus
from returnops.errors import ExternalSystemFailure, NotFound
from returnops.models import RefundAttempt, ReturnCase
from returnops.services.audit import record_audit
from returnops.services.returns import system_transition


@dataclass(frozen=True)
class ProviderRefundResult:
    provider_ref: str
    status: str
    raw: dict[str, Any]


class PaymentProviderClient:
    def __init__(self, base_url: str | None = None, transport: httpx.BaseTransport | None = None) -> None:
        self.base_url = (base_url or get_settings().payment_base_url).rstrip("/")
        self.transport = transport

    def create_refund(
        self,
        *,
        idempotency_key: str,
        amount_minor: int,
        currency: str,
        return_case_id: uuid.UUID,
    ) -> ProviderRefundResult:
        with httpx.Client(base_url=self.base_url, timeout=3.0, transport=self.transport) as client:
            response = client.post(
                "/refunds",
                headers={
                    "Idempotency-Key": idempotency_key,
                    "X-Simulate": get_settings().payment_simulation_mode,
                },
                json={
                    "amount_minor": amount_minor,
                    "currency": currency,
                    "return_case_id": str(return_case_id),
                },
            )
        if response.status_code == 503:
            raise ExternalSystemFailure("provider declared a safe-to-retry pre-processing failure")
        response.raise_for_status()
        body = response.json()
        return ProviderRefundResult(
            provider_ref=str(body["refund_id"]),
            status=str(body["status"]),
            raw=body,
        )

    def lookup_by_idempotency_key(self, idempotency_key: str) -> ProviderRefundResult | None:
        with httpx.Client(base_url=self.base_url, timeout=3.0, transport=self.transport) as client:
            response = client.get("/refunds/by-idempotency-key", params={"key": idempotency_key})
        if response.status_code == 404:
            return None
        response.raise_for_status()
        body = response.json()
        return ProviderRefundResult(
            provider_ref=str(body["refund_id"]),
            status=str(body["status"]),
            raw=body,
        )


def get_refund_attempt(db: Session, attempt_id: uuid.UUID) -> RefundAttempt:
    attempt = db.get(RefundAttempt, attempt_id)
    if attempt is None:
        raise NotFound("refund attempt not found")
    return attempt


def _load_case_for_attempt(db: Session, attempt: RefundAttempt) -> ReturnCase:
    case = db.execute(
        select(ReturnCase).where(
            ReturnCase.id == attempt.return_case_id,
            ReturnCase.organization_id == attempt.organization_id,
        )
    ).scalar_one()
    return case


def mark_dispatching(db: Session, attempt: RefundAttempt) -> None:
    if attempt.status not in {RefundAttemptStatus.PLANNED, RefundAttemptStatus.FAILED}:
        raise RuntimeError(f"cannot dispatch attempt in {attempt.status.value}")
    attempt.status = RefundAttemptStatus.DISPATCHING
    attempt.dispatch_count += 1
    attempt.last_error = None
    db.flush()


def mark_known_failure(db: Session, attempt: RefundAttempt, *, error: str) -> None:
    attempt.status = RefundAttemptStatus.FAILED
    attempt.last_error = error[:2000]
    db.flush()
    record_audit(
        db,
        organization_id=attempt.organization_id,
        actor_user_id=None,
        action="refund.dispatch_known_failure",
        resource_type="refund_attempt",
        resource_id=str(attempt.id),
        metadata={"error": error, "dispatch_count": attempt.dispatch_count},
    )


def mark_unknown(db: Session, attempt: RefundAttempt, *, error: str) -> None:
    attempt.status = RefundAttemptStatus.UNKNOWN
    attempt.last_error = error[:2000]
    db.flush()
    case = _load_case_for_attempt(db, attempt)
    if case.status is ReturnStatus.REFUND_PENDING:
        system_transition(
            db,
            case=case,
            target=ReturnStatus.REFUND_UNKNOWN,
            metadata={"refund_attempt_id": str(attempt.id), "error": error[:500]},
        )
    record_audit(
        db,
        organization_id=attempt.organization_id,
        actor_user_id=None,
        action="refund.outcome_unknown",
        resource_type="refund_attempt",
        resource_id=str(attempt.id),
        metadata={"error": error},
    )


def mark_success(
    db: Session,
    attempt: RefundAttempt,
    *,
    provider_ref: str,
    evidence: dict[str, Any],
    evidence_source: str,
) -> None:
    attempt.status = RefundAttemptStatus.SUCCEEDED
    attempt.provider_ref = provider_ref
    attempt.evidence_json = evidence
    attempt.last_error = None
    db.flush()
    case = _load_case_for_attempt(db, attempt)
    if case.status in {
        ReturnStatus.REFUND_PENDING,
        ReturnStatus.REFUND_UNKNOWN,
        ReturnStatus.NEEDS_RECONCILIATION,
    }:
        system_transition(
            db,
            case=case,
            target=ReturnStatus.REFUNDED,
            metadata={
                "refund_attempt_id": str(attempt.id),
                "provider_ref": provider_ref,
                "evidence_source": evidence_source,
            },
        )
    record_audit(
        db,
        organization_id=attempt.organization_id,
        actor_user_id=None,
        action="refund.provider_confirmed",
        resource_type="refund_attempt",
        resource_id=str(attempt.id),
        metadata={"provider_ref": provider_ref, "evidence_source": evidence_source},
    )


def mark_manual_reconciliation_needed(db: Session, attempt: RefundAttempt, *, reason: str) -> None:
    case = _load_case_for_attempt(db, attempt)
    if case.status in {ReturnStatus.REFUND_PENDING, ReturnStatus.REFUND_UNKNOWN}:
        system_transition(
            db,
            case=case,
            target=ReturnStatus.NEEDS_RECONCILIATION,
            metadata={"refund_attempt_id": str(attempt.id), "reason": reason},
        )
    record_audit(
        db,
        organization_id=attempt.organization_id,
        actor_user_id=None,
        action="refund.manual_reconciliation_required",
        resource_type="refund_attempt",
        resource_id=str(attempt.id),
        metadata={"reason": reason},
    )


def mark_authoritatively_not_found(
    db: Session,
    attempt: RefundAttempt,
    *,
    evidence: dict[str, Any] | None = None,
) -> None:
    """Convert UNKNOWN into known failure after an authoritative negative lookup.

    This is intentionally different from treating a network timeout as failure. The
    provider lookup is the new evidence that makes a human-approved retry safe.
    """
    attempt.status = RefundAttemptStatus.FAILED
    attempt.last_error = "authoritative provider lookup found no refund"
    attempt.evidence_json = evidence or {"lookup": "not_found"}
    db.flush()
    mark_manual_reconciliation_needed(
        db,
        attempt,
        reason="provider authoritatively reported no matching refund; explicit retry is now allowed",
    )
