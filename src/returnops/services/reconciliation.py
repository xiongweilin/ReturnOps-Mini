from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from returnops.domain.states import RefundAttemptStatus, ReturnStatus, Role
from returnops.errors import Conflict, NotFound
from returnops.models import RefundAttempt, ReturnCase
from returnops.services.payments import (
    PaymentProviderClient,
    mark_authoritatively_not_found,
    mark_manual_reconciliation_needed,
    mark_success,
)
from returnops.services.tenancy import TenantContext, require_role


def reconcile_unknown_refund(
    db: Session,
    *,
    context: TenantContext,
    case_id: uuid.UUID,
    provider: PaymentProviderClient,
) -> dict:
    require_role(context, Role.FINANCE)
    case = db.execute(
        select(ReturnCase).where(
            ReturnCase.id == case_id,
            ReturnCase.organization_id == context.organization_id,
        )
    ).scalar_one_or_none()
    if case is None:
        raise NotFound("return case not found")
    if case.status not in {ReturnStatus.REFUND_UNKNOWN, ReturnStatus.NEEDS_RECONCILIATION}:
        raise Conflict("manual provider reconciliation is only for uncertain refunds")

    attempt = db.execute(
        select(RefundAttempt).where(
            RefundAttempt.return_case_id == case.id,
            RefundAttempt.organization_id == context.organization_id,
        )
    ).scalar_one_or_none()
    if attempt is None:
        raise NotFound("refund attempt not found")

    observed = provider.lookup_by_idempotency_key(attempt.provider_idempotency_key)
    if observed is not None:
        if observed.status == "succeeded":
            mark_success(
                db,
                attempt,
                provider_ref=observed.provider_ref,
                evidence=observed.raw,
                evidence_source="manual_provider_lookup",
            )
            return {
                "resolution": "provider_confirmed_success",
                "providerRef": observed.provider_ref,
            }

        # "存在但不是成功" 与 "权威查询确认不存在" 是不同事实。
        # 对未知/处理中等非终态不能擅自推导成失败并开放重试。
        mark_manual_reconciliation_needed(
            db,
            attempt,
            reason=f"provider returned non-success status: {observed.status}",
        )
        return {
            "resolution": "provider_non_terminal_or_unrecognized",
            "providerRef": observed.provider_ref,
            "providerStatus": observed.status,
        }

    if attempt.status is RefundAttemptStatus.UNKNOWN:
        mark_authoritatively_not_found(db, attempt)
        return {"resolution": "provider_confirmed_absent", "providerRef": None}
    mark_manual_reconciliation_needed(
        db,
        attempt,
        reason="provider did not confirm success",
    )
    return {"resolution": "manual_review_required", "providerRef": None}
