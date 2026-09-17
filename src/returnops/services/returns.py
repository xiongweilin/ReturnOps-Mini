from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from returnops.domain.states import ApprovalDecision, ApprovalKind, ReturnStatus, Role
from returnops.errors import Conflict, PermissionDenied
from returnops.models import Approval, ReturnCase
from returnops.services.case_store import (
    _cas_transition,
    case_view,
    create_case,
    get_case,
    list_cases,
    system_transition,
)
from returnops.services.tenancy import TenantContext, require_role

def authorize_case(
    db: Session,
    *,
    context: TenantContext,
    case_id: uuid.UUID,
    expected_version: int,
    rationale: str | None,
) -> ReturnCase:
    require_role(context, Role.CUSTOMER_SERVICE)
    case = get_case(db, context=context, case_id=case_id)
    updated = _cas_transition(
        db,
        case=case,
        target=ReturnStatus.AUTHORIZED,
        context=context,
        expected_version=expected_version,
        audit_action="return.authorized",
    )
    db.add(
        Approval(
            organization_id=context.organization_id,
            return_case_id=case.id,
            kind=ApprovalKind.ELIGIBILITY,
            decision=ApprovalDecision.APPROVED,
            user_id=context.user_id,
            rationale=rationale,
        )
    )
    return updated

def receive_case(
    db: Session,
    *,
    context: TenantContext,
    case_id: uuid.UUID,
    expected_version: int,
) -> ReturnCase:
    require_role(context, Role.WAREHOUSE)
    case = get_case(db, context=context, case_id=case_id)
    return _cas_transition(
        db,
        case=case,
        target=ReturnStatus.RECEIVED,
        context=context,
        expected_version=expected_version,
        audit_action="return.received",
    )

def inspect_case(
    db: Session,
    *,
    context: TenantContext,
    case_id: uuid.UUID,
    expected_version: int,
    notes: str,
) -> ReturnCase:
    require_role(context, Role.WAREHOUSE)
    case = get_case(db, context=context, case_id=case_id)
    return _cas_transition(
        db,
        case=case,
        target=ReturnStatus.INSPECTED,
        context=context,
        expected_version=expected_version,
        values={"inspection_notes": notes},
        audit_action="return.inspected",
    )

def reject_case(
    db: Session,
    *,
    context: TenantContext,
    case_id: uuid.UUID,
    expected_version: int,
    reason: str,
) -> ReturnCase:
    case = get_case(db, context=context, case_id=case_id)
    if context.role not in {Role.CUSTOMER_SERVICE, Role.FINANCE, Role.ADMIN}:
        raise PermissionDenied("current role cannot reject a return")
    if case.status not in {
        ReturnStatus.REQUESTED,
        ReturnStatus.INSPECTED,
    }:
        raise Conflict(f"cannot reject return from {case.status.value}")
    return _cas_transition(
        db,
        case=case,
        target=ReturnStatus.REJECTED,
        context=context,
        expected_version=expected_version,
        values={"rejection_reason": reason},
        audit_action="return.rejected",
    )

def reconcile_case(
    db: Session,
    *,
    context: TenantContext,
    case_id: uuid.UUID,
    expected_version: int,
) -> ReturnCase:
    require_role(context, Role.FINANCE)
    case = get_case(db, context=context, case_id=case_id)
    return _cas_transition(
        db,
        case=case,
        target=ReturnStatus.RECONCILED,
        context=context,
        expected_version=expected_version,
        audit_action="return.reconciled",
    )

def close_case(
    db: Session,
    *,
    context: TenantContext,
    case_id: uuid.UUID,
    expected_version: int,
) -> ReturnCase:
    require_role(context, Role.FINANCE)
    case = get_case(db, context=context, case_id=case_id)
    return _cas_transition(
        db,
        case=case,
        target=ReturnStatus.CLOSED,
        context=context,
        expected_version=expected_version,
        audit_action="return.closed",
    )

from returnops.services.refunds import approve_refund, retry_failed_refund

__all__ = [
    "approve_refund", "authorize_case", "case_view", "close_case", "create_case",
    "get_case", "inspect_case", "list_cases", "receive_case", "reconcile_case",
    "reject_case", "retry_failed_refund", "system_transition",
]
