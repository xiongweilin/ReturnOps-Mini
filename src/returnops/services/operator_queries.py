from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from returnops.domain.states import (
    ApprovalDecision,
    ApprovalKind,
    RefundAttemptStatus,
    ReturnStatus,
    Role,
)
from returnops.models import Approval, AuditEvent, OutboxEvent, RefundAttempt, ReturnCase
from returnops.services.case_store import case_view, list_cases
from returnops.services.tenancy import TenantContext


ATTENTION_OWNER_BY_STATUS: dict[ReturnStatus, tuple[str, str]] = {
    ReturnStatus.REQUESTED: ("客服", "审核退货申请"),
    ReturnStatus.AUTHORIZED: ("仓库", "确认收货"),
    ReturnStatus.RECEIVED: ("仓库", "提交验货结果"),
    ReturnStatus.INSPECTED: ("财务", "审批退款"),
    ReturnStatus.REFUND_UNKNOWN: ("财务", "查询支付方状态"),
    ReturnStatus.NEEDS_RECONCILIATION: ("财务", "核对退款结果"),
    ReturnStatus.REFUNDED: ("财务", "完成退款对账"),
    ReturnStatus.RECONCILED: ("财务", "结案"),
}

EXCEPTION_STATUSES = (
    ReturnStatus.REFUND_UNKNOWN,
    ReturnStatus.NEEDS_RECONCILIATION,
    ReturnStatus.REFUNDED,
)


def allowed_actions(
    case: ReturnCase,
    *,
    context: TenantContext,
    attempt: RefundAttempt | None,
    approvals: list[Approval],
) -> list[str]:
    role = context.role
    is_admin = role is Role.ADMIN
    actions: list[str] = []
    if case.status is ReturnStatus.REQUESTED and (is_admin or role is Role.CUSTOMER_SERVICE):
        actions.extend(("authorize", "reject"))
    elif case.status is ReturnStatus.AUTHORIZED and (is_admin or role is Role.WAREHOUSE):
        actions.append("receive")
    elif case.status is ReturnStatus.RECEIVED and (is_admin or role is Role.WAREHOUSE):
        actions.append("inspect")
    elif case.status is ReturnStatus.INSPECTED:
        refund_approvals = [
            row
            for row in approvals
            if row.kind in {ApprovalKind.REFUND, ApprovalKind.HIGH_VALUE_REFUND_SECOND}
            and row.decision is ApprovalDecision.APPROVED
        ]
        distinct_approver = all(row.user_id != context.user_id for row in refund_approvals)
        if (is_admin or role is Role.FINANCE) and len(refund_approvals) < 2 and distinct_approver:
            actions.append("approve_refund")
        if is_admin or role in {Role.CUSTOMER_SERVICE, Role.FINANCE}:
            actions.append("reject")
    elif case.status in {ReturnStatus.REFUND_UNKNOWN, ReturnStatus.NEEDS_RECONCILIATION}:
        if is_admin or role is Role.FINANCE:
            if attempt is not None and attempt.status is RefundAttemptStatus.UNKNOWN:
                actions.append("provider_reconcile")
            if attempt is not None and attempt.status is RefundAttemptStatus.FAILED:
                actions.append("retry_failed_refund")
    elif case.status is ReturnStatus.REFUNDED and (is_admin or role is Role.FINANCE):
        actions.append("mark_reconciled")
    elif case.status is ReturnStatus.RECONCILED and (is_admin or role is Role.FINANCE):
        actions.append("close")
    return actions


def case_detail_view(db: Session, *, context: TenantContext, case: ReturnCase) -> dict[str, Any]:
    result = case_view(case)
    approvals = list(
        db.execute(
            select(Approval)
            .where(
                Approval.organization_id == context.organization_id,
                Approval.return_case_id == case.id,
            )
            .order_by(Approval.created_at)
        )
        .scalars()
        .all()
    )
    attempts = list(
        db.execute(
            select(RefundAttempt)
            .where(
                RefundAttempt.organization_id == context.organization_id,
                RefundAttempt.return_case_id == case.id,
            )
            .order_by(RefundAttempt.created_at)
        )
        .scalars()
        .all()
    )
    attempt_ids = [str(attempt.id) for attempt in attempts]
    resource_filter = AuditEvent.resource_id == str(case.id)
    if attempt_ids:
        resource_filter = or_(resource_filter, AuditEvent.resource_id.in_(attempt_ids))
    audit_events = list(
        db.execute(
            select(AuditEvent)
            .where(
                AuditEvent.organization_id == context.organization_id,
                resource_filter,
            )
            .order_by(AuditEvent.created_at)
            .limit(200)
        )
        .scalars()
        .all()
    )
    outbox_events = (
        list(
            db.execute(
                select(OutboxEvent)
                .where(
                    OutboxEvent.organization_id == context.organization_id,
                    OutboxEvent.aggregate_id.in_(attempt_ids),
                )
                .order_by(OutboxEvent.created_at)
            )
            .scalars()
            .all()
        )
        if attempt_ids
        else []
    )

    result["approvals"] = [
        {
            "id": str(row.id),
            "kind": row.kind.value,
            "decision": row.decision.value,
            "userId": str(row.user_id),
            "amountMinor": row.amount_minor,
            "rationale": row.rationale,
            "createdAt": row.created_at.isoformat(),
        }
        for row in approvals
    ]
    result["refundAttempts"] = [
        {
            "id": str(row.id),
            "status": row.status.value,
            "providerRef": row.provider_ref,
            "providerIdempotencyKey": row.provider_idempotency_key,
            "amountMinor": row.amount_minor,
            "currency": row.currency,
            "dispatchCount": row.dispatch_count,
            "lastError": row.last_error,
            "evidence": row.evidence_json,
            "createdAt": row.created_at.isoformat(),
            "updatedAt": row.updated_at.isoformat(),
        }
        for row in attempts
    ]
    result["outboxEvents"] = [
        {
            "id": str(row.id),
            "topic": row.topic,
            "status": row.status,
            "attempts": row.attempts,
            "lastError": row.last_error,
            "createdAt": row.created_at.isoformat(),
            "updatedAt": row.updated_at.isoformat(),
        }
        for row in outbox_events
    ]
    result["auditEvents"] = [
        {
            "id": str(row.id),
            "actorUserId": str(row.actor_user_id) if row.actor_user_id else None,
            "action": row.action,
            "resourceType": row.resource_type,
            "resourceId": row.resource_id,
            "before": row.before_json,
            "after": row.after_json,
            "metadata": row.metadata_json,
            "createdAt": row.created_at.isoformat(),
        }
        for row in audit_events
    ]
    result["allowedActions"] = allowed_actions(
        case,
        context=context,
        attempt=attempts[-1] if attempts else None,
        approvals=approvals,
    )
    return result


def exception_cases(db: Session, *, context: TenantContext, limit: int = 100) -> list[ReturnCase]:
    stmt = (
        select(ReturnCase)
        .outerjoin(
            RefundAttempt,
            and_(
                RefundAttempt.return_case_id == ReturnCase.id,
                RefundAttempt.organization_id == ReturnCase.organization_id,
            ),
        )
        .where(
            ReturnCase.organization_id == context.organization_id,
            or_(
                ReturnCase.status.in_(EXCEPTION_STATUSES),
                RefundAttempt.status.in_((RefundAttemptStatus.UNKNOWN, RefundAttemptStatus.FAILED)),
            ),
        )
        .order_by(ReturnCase.updated_at.desc())
        .limit(max(1, min(limit, 200)))
    )
    return list(db.execute(stmt).unique().scalars().all())


def exception_case_count(db: Session, *, context: TenantContext) -> int:
    stmt = (
        select(func.count(func.distinct(ReturnCase.id)))
        .select_from(ReturnCase)
        .outerjoin(
            RefundAttempt,
            and_(
                RefundAttempt.return_case_id == ReturnCase.id,
                RefundAttempt.organization_id == ReturnCase.organization_id,
            ),
        )
        .where(
            ReturnCase.organization_id == context.organization_id,
            or_(
                ReturnCase.status.in_(EXCEPTION_STATUSES),
                RefundAttempt.status.in_((RefundAttemptStatus.UNKNOWN, RefundAttemptStatus.FAILED)),
            ),
        )
    )
    return int(db.execute(stmt).scalar_one())


def attention_items(
    db: Session, *, context: TenantContext, limit: int = 20
) -> list[dict[str, Any]]:
    stmt = (
        select(ReturnCase)
        .where(
            ReturnCase.organization_id == context.organization_id,
            ReturnCase.status.in_(tuple(ATTENTION_OWNER_BY_STATUS)),
        )
        .order_by(ReturnCase.updated_at, ReturnCase.created_at)
        .limit(max(1, min(limit, 50)))
    )
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "id": str(case.id),
            "caseRef": case.case_ref,
            "externalOrderRef": case.external_order_ref,
            "status": case.status.value,
            "ownerRole": ATTENTION_OWNER_BY_STATUS[case.status][0],
            "nextAction": ATTENTION_OWNER_BY_STATUS[case.status][1],
            "updatedAt": case.updated_at.isoformat(),
        }
        for case in rows
    ]


def overview(db: Session, *, context: TenantContext) -> dict[str, Any]:
    grouped = db.execute(
        select(ReturnCase.status, func.count())
        .where(ReturnCase.organization_id == context.organization_id)
        .group_by(ReturnCase.status)
    ).all()
    counts = {status: count for status, count in grouped}
    pending_warehouse = counts.get(ReturnStatus.AUTHORIZED, 0) + counts.get(
        ReturnStatus.RECEIVED, 0
    )
    exceptions = exception_cases(db, context=context, limit=10)
    return {
        "total": sum(counts.values()),
        "pendingCustomerService": counts.get(ReturnStatus.REQUESTED, 0),
        "pendingWarehouse": pending_warehouse,
        "pendingFinance": counts.get(ReturnStatus.INSPECTED, 0),
        "refundProcessing": counts.get(ReturnStatus.REFUND_PENDING, 0),
        "refundExceptions": exception_case_count(db, context=context),
        "closed": counts.get(ReturnStatus.CLOSED, 0),
        "recentReturns": [case_view(case) for case in list_cases(db, context=context, limit=10)],
        "recentExceptions": [case_view(case) for case in exceptions],
        "attentionItems": attention_items(db, context=context),
    }
