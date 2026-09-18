from __future__ import annotations

import uuid
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.orm import Session

from returnops.domain.states import (
    ReturnStatus,
    Role,
    assert_actor_can_transition,
    assert_transition,
)
from returnops.errors import Conflict, NotFound, VersionConflict
from returnops.models import ReturnCase, utcnow
from returnops.services.audit import record_audit
from returnops.services.tenancy import TenantContext, require_role


def case_view(case: ReturnCase) -> dict[str, Any]:
    return {
        "id": str(case.id),
        "organizationId": str(case.organization_id),
        "caseRef": case.case_ref,
        "externalOrderRef": case.external_order_ref,
        "customerRef": case.customer_ref,
        "reason": case.reason,
        "requestedAmountMinor": case.requested_amount_minor,
        "approvedAmountMinor": case.approved_amount_minor,
        "currency": case.currency,
        "status": case.status.value,
        "version": case.version,
        "inspectionNotes": case.inspection_notes,
        "rejectionReason": case.rejection_reason,
        "createdAt": case.created_at.isoformat(),
        "updatedAt": case.updated_at.isoformat(),
    }


def get_case(db: Session, *, context: TenantContext, case_id: uuid.UUID) -> ReturnCase:
    case = db.execute(
        select(ReturnCase).where(
            ReturnCase.id == case_id,
            ReturnCase.organization_id == context.organization_id,
        )
    ).scalar_one_or_none()
    if case is None:
        # Deliberately return 404 for cross-tenant ids to avoid leaking existence.
        raise NotFound("return case not found")
    return case


def list_cases(
    db: Session,
    *,
    context: TenantContext,
    status: ReturnStatus | None = None,
    limit: int = 50,
) -> list[ReturnCase]:
    stmt = select(ReturnCase).where(ReturnCase.organization_id == context.organization_id)
    if status is not None:
        stmt = stmt.where(ReturnCase.status == status)
    stmt = stmt.order_by(ReturnCase.created_at.desc()).limit(max(1, min(limit, 200)))
    return list(db.execute(stmt).scalars().all())


def create_case(
    db: Session,
    *,
    context: TenantContext,
    external_order_ref: str,
    customer_ref: str,
    reason: str,
    requested_amount_minor: int,
    currency: str,
) -> ReturnCase:
    require_role(context, Role.CUSTOMER_SERVICE)
    if requested_amount_minor <= 0:
        raise Conflict("requested amount must be positive")
    case = ReturnCase(
        organization_id=context.organization_id,
        case_ref=f"RET-{uuid.uuid4().hex[:10].upper()}",
        external_order_ref=external_order_ref,
        customer_ref=customer_ref,
        reason=reason,
        requested_amount_minor=requested_amount_minor,
        currency=currency.upper(),
        status=ReturnStatus.REQUESTED,
        created_by_user_id=context.user_id,
    )
    db.add(case)
    db.flush()
    record_audit(
        db,
        organization_id=context.organization_id,
        actor_user_id=context.user_id,
        action="return.created",
        resource_type="return_case",
        resource_id=str(case.id),
        after=case_view(case),
    )
    return case


def _cas_transition(
    db: Session,
    *,
    case: ReturnCase,
    target: ReturnStatus,
    context: TenantContext | None,
    system: bool = False,
    expected_version: int | None = None,
    values: dict[str, Any] | None = None,
    audit_action: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ReturnCase:
    expected = expected_version if expected_version is not None else case.version
    if expected != case.version:
        raise VersionConflict(f"expected version {expected}, current version is {case.version}")
    assert_transition(case.status, target)
    role = None if context is None else context.role
    assert_actor_can_transition(role, target, system=system)

    before = case_view(case)
    update_values: dict[str, Any] = {
        "status": target,
        "version": case.version + 1,
        "updated_at": utcnow(),
    }
    update_values.update(values or {})
    result = db.execute(
        update(ReturnCase)
        .where(
            ReturnCase.id == case.id,
            ReturnCase.organization_id == case.organization_id,
            ReturnCase.version == case.version,
            ReturnCase.status == case.status,
        )
        .values(**update_values)
    )
    affected = cast(CursorResult[Any], result).rowcount
    if affected != 1:
        raise VersionConflict("return case changed concurrently; reload and retry")
    db.flush()
    db.expire(case)
    db.refresh(case)

    record_audit(
        db,
        organization_id=case.organization_id,
        actor_user_id=None if context is None else context.user_id,
        action=audit_action or f"return.transition.{target.value}",
        resource_type="return_case",
        resource_id=str(case.id),
        before=before,
        after=case_view(case),
        metadata=metadata,
    )
    return case


def system_transition(
    db: Session,
    *,
    case: ReturnCase,
    target: ReturnStatus,
    metadata: dict[str, Any] | None = None,
) -> ReturnCase:
    return _cas_transition(
        db,
        case=case,
        target=target,
        context=None,
        system=True,
        audit_action=f"system.return.{target.value}",
        metadata=metadata,
    )
