from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from returnops.config import get_settings
from returnops.domain.states import ApprovalDecision, ApprovalKind, ReturnStatus, Role, assert_approved_amount
from returnops.errors import Conflict, PermissionDenied, VersionConflict
from returnops.models import Approval, RefundAttempt, ReturnCase, utcnow
from returnops.services.audit import record_audit
from returnops.services.case_store import _cas_transition, get_case
from returnops.services.outbox import TOPIC_REFUND_DISPATCH, enqueue
from returnops.services.tenancy import TenantContext, require_role


def _refund_approvals(db: Session, case_id: uuid.UUID) -> list[Approval]:
    return list(
        db.execute(
            select(Approval)
            .where(
                Approval.return_case_id == case_id,
                Approval.kind.in_((ApprovalKind.REFUND, ApprovalKind.HIGH_VALUE_REFUND_SECOND)),
                Approval.decision == ApprovalDecision.APPROVED,
            )
            .order_by(Approval.created_at)
        )
        .scalars()
        .all()
    )


def approve_refund(
    db: Session,
    *,
    context: TenantContext,
    case_id: uuid.UUID,
    expected_version: int,
    approved_amount_minor: int,
    rationale: str | None,
) -> tuple[ReturnCase, bool]:
    require_role(context, Role.FINANCE)
    case = get_case(db, context=context, case_id=case_id)
    if case.status is not ReturnStatus.INSPECTED:
        raise Conflict("refund approval requires inspected status")
    if expected_version != case.version:
        raise VersionConflict(f"expected version {expected_version}, current version is {case.version}")
    assert_approved_amount(case.requested_amount_minor, approved_amount_minor)

    approvals = _refund_approvals(db, case.id)
    threshold = get_settings().high_value_threshold
    high_value = approved_amount_minor >= threshold

    if not approvals:
        first = Approval(
            organization_id=context.organization_id,
            return_case_id=case.id,
            kind=ApprovalKind.REFUND,
            decision=ApprovalDecision.APPROVED,
            user_id=context.user_id,
            amount_minor=approved_amount_minor,
            rationale=rationale,
        )
        if high_value:
            result = db.execute(
                update(ReturnCase)
                .where(
                    ReturnCase.id == case.id,
                    ReturnCase.organization_id == case.organization_id,
                    ReturnCase.version == expected_version,
                    ReturnCase.status == ReturnStatus.INSPECTED,
                )
                .values(version=expected_version + 1, updated_at=utcnow())
            )
            if result.rowcount != 1:
                raise VersionConflict("return case changed concurrently; reload and retry")
            db.add(first)
            db.flush()
            db.expire(case)
            db.refresh(case)
            record_audit(
                db,
                organization_id=context.organization_id,
                actor_user_id=context.user_id,
                action="refund.first_approval_recorded",
                resource_type="return_case",
                resource_id=str(case.id),
                metadata={"amount_minor": approved_amount_minor, "second_approval_required": True},
            )
            return case, True
        db.add(first)
        db.flush()
    else:
        first = approvals[0]
        if not high_value:
            raise Conflict("refund is already approved")
        if first.amount_minor != approved_amount_minor:
            raise Conflict("second approval amount must match the first approval")
        if first.user_id == context.user_id:
            raise PermissionDenied("high-value refund requires a distinct second approver")
        if len(approvals) >= 2:
            raise Conflict("high-value refund already has two approvals")
        db.add(
            Approval(
                organization_id=context.organization_id,
                return_case_id=case.id,
                kind=ApprovalKind.HIGH_VALUE_REFUND_SECOND,
                decision=ApprovalDecision.APPROVED,
                user_id=context.user_id,
                amount_minor=approved_amount_minor,
                rationale=rationale,
            )
        )
        db.flush()

    updated = _cas_transition(
        db,
        case=case,
        target=ReturnStatus.REFUND_APPROVED,
        context=context,
        expected_version=expected_version,
        values={"approved_amount_minor": approved_amount_minor},
        audit_action="refund.approved",
        metadata={"amount_minor": approved_amount_minor, "high_value": high_value},
    )
    _plan_refund(db, case=updated)
    return updated, False


def _plan_refund(db: Session, *, case: ReturnCase) -> RefundAttempt:
    if case.approved_amount_minor is None:
        raise Conflict("approved amount missing")
    existing = db.execute(
        select(RefundAttempt).where(RefundAttempt.return_case_id == case.id)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    attempt = RefundAttempt(
        organization_id=case.organization_id,
        return_case_id=case.id,
        provider_idempotency_key=f"return:{case.id}:refund:v1",
        amount_minor=case.approved_amount_minor,
        currency=case.currency,
    )
    db.add(attempt)
    db.flush()
    _cas_transition(
        db,
        case=case,
        target=ReturnStatus.REFUND_PENDING,
        context=None,
        system=True,
        expected_version=case.version,
        audit_action="refund.planned",
        metadata={"refund_attempt_id": str(attempt.id)},
    )
    enqueue(
        db,
        organization_id=case.organization_id,
        topic=TOPIC_REFUND_DISPATCH,
        aggregate_type="refund_attempt",
        aggregate_id=str(attempt.id),
        payload={"refund_attempt_id": str(attempt.id)},
    )
    return attempt


def retry_failed_refund(
    db: Session,
    *,
    context: TenantContext,
    case_id: uuid.UUID,
    expected_version: int,
) -> ReturnCase:
    require_role(context, Role.FINANCE)
    case = get_case(db, context=context, case_id=case_id)
    if case.status is not ReturnStatus.NEEDS_RECONCILIATION:
        raise Conflict("retry requires needs_reconciliation status")
    if expected_version != case.version:
        raise VersionConflict(f"expected version {expected_version}, current version is {case.version}")
    attempt = db.execute(
        select(RefundAttempt).where(
            RefundAttempt.return_case_id == case.id,
            RefundAttempt.organization_id == context.organization_id,
        )
    ).scalar_one_or_none()
    if attempt is None:
        raise Conflict("refund attempt missing")
    if attempt.status.value != "failed":
        raise Conflict("only a known failed refund may be retried; unknown outcomes must be reconciled")

    attempt.status = type(attempt.status).PLANNED
    attempt.last_error = None
    updated = _cas_transition(
        db,
        case=case,
        target=ReturnStatus.REFUND_PENDING,
        context=None,
        system=True,
        expected_version=expected_version,
        audit_action="refund.retry_authorized",
        metadata={"authorized_by_user_id": str(context.user_id)},
    )
    enqueue(
        db,
        organization_id=context.organization_id,
        topic=TOPIC_REFUND_DISPATCH,
        aggregate_type="refund_attempt",
        aggregate_id=str(attempt.id),
        payload={"refund_attempt_id": str(attempt.id), "manual_retry": True},
    )
    return updated
