from __future__ import annotations

import uuid
from typing import Annotated, Any, Callable

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from returnops.config import get_settings
from returnops.db import get_session
from returnops.domain.states import ReturnStatus
from returnops.errors import PermissionDenied
from returnops.schemas import (
    ApproveRefundRequest,
    AuthorizeRequest,
    InspectRequest,
    RejectRequest,
    ReturnCreate,
    VersionedAction,
)
from returnops.security import secure_equal
from returnops.services.idempotency import claim, complete
from returnops.services.payments import PaymentProviderClient
from returnops.services.reconciliation import reconcile_unknown_refund
from returnops.services.returns import (
    approve_refund,
    authorize_case,
    case_view,
    close_case,
    create_case,
    get_case,
    inspect_case,
    list_cases,
    receive_case,
    reconcile_case,
    reject_case,
    retry_failed_refund,
)
from returnops.services.tenancy import TenantContext
from returnops.services.webhooks import process_payment_webhook
from returnops.api.deps import tenant_context

router = APIRouter(prefix="/v1")


def _idem(
    db: Session,
    *,
    context: TenantContext,
    key: str,
    scope: str,
    payload: dict[str, Any],
    operation: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    claimed = claim(
        db,
        organization_id=context.organization_id,
        scope=scope,
        key=key,
        request_payload=payload,
    )
    if claimed.replay is not None:
        return {"replayed": True, "result": claimed.replay}
    result = operation()
    complete(claimed, result)
    db.flush()
    return {"replayed": False, "result": result}


@router.get("/returns")
def returns_list(
    context: Annotated[TenantContext, Depends(tenant_context)],
    db: Annotated[Session, Depends(get_session)],
    status: ReturnStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    return {"items": [case_view(row) for row in list_cases(db, context=context, status=status, limit=limit)]}


@router.get("/returns/{case_id}")
def returns_get(
    case_id: uuid.UUID,
    context: Annotated[TenantContext, Depends(tenant_context)],
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    return case_view(get_case(db, context=context, case_id=case_id))


@router.post("/returns", status_code=201)
def returns_create(
    body: ReturnCreate,
    context: Annotated[TenantContext, Depends(tenant_context)],
    db: Annotated[Session, Depends(get_session)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, Any]:
    payload = body.model_dump(mode="json")
    return _idem(
        db,
        context=context,
        key=idempotency_key,
        scope="return.create",
        payload=payload,
        operation=lambda: case_view(create_case(db, context=context, **payload)),
    )


@router.post("/returns/{case_id}/authorize")
def returns_authorize(
    case_id: uuid.UUID,
    body: AuthorizeRequest,
    context: Annotated[TenantContext, Depends(tenant_context)],
    db: Annotated[Session, Depends(get_session)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, Any]:
    payload = {"case_id": str(case_id), **body.model_dump(mode="json")}
    return _idem(
        db,
        context=context,
        key=idempotency_key,
        scope=f"return.authorize:{case_id}",
        payload=payload,
        operation=lambda: case_view(
            authorize_case(
                db,
                context=context,
                case_id=case_id,
                expected_version=body.expected_version,
                rationale=body.rationale,
            )
        ),
    )


@router.post("/returns/{case_id}/receive")
def returns_receive(
    case_id: uuid.UUID,
    body: VersionedAction,
    context: Annotated[TenantContext, Depends(tenant_context)],
    db: Annotated[Session, Depends(get_session)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, Any]:
    payload = {"case_id": str(case_id), **body.model_dump()}
    return _idem(
        db,
        context=context,
        key=idempotency_key,
        scope=f"return.receive:{case_id}",
        payload=payload,
        operation=lambda: case_view(
            receive_case(
                db,
                context=context,
                case_id=case_id,
                expected_version=body.expected_version,
            )
        ),
    )


@router.post("/returns/{case_id}/inspect")
def returns_inspect(
    case_id: uuid.UUID,
    body: InspectRequest,
    context: Annotated[TenantContext, Depends(tenant_context)],
    db: Annotated[Session, Depends(get_session)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, Any]:
    payload = {"case_id": str(case_id), **body.model_dump()}
    return _idem(
        db,
        context=context,
        key=idempotency_key,
        scope=f"return.inspect:{case_id}",
        payload=payload,
        operation=lambda: case_view(
            inspect_case(
                db,
                context=context,
                case_id=case_id,
                expected_version=body.expected_version,
                notes=body.notes,
            )
        ),
    )


@router.post("/returns/{case_id}/approve-refund")
def returns_approve_refund(
    case_id: uuid.UUID,
    body: ApproveRefundRequest,
    context: Annotated[TenantContext, Depends(tenant_context)],
    db: Annotated[Session, Depends(get_session)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, Any]:
    payload = {"case_id": str(case_id), **body.model_dump()}

    def op() -> dict[str, Any]:
        case, needs_second = approve_refund(
            db,
            context=context,
            case_id=case_id,
            expected_version=body.expected_version,
            approved_amount_minor=body.approved_amount_minor,
            rationale=body.rationale,
        )
        return {"case": case_view(case), "secondApprovalRequired": needs_second}

    return _idem(
        db,
        context=context,
        key=idempotency_key,
        scope=f"return.approve_refund:{case_id}",
        payload=payload,
        operation=op,
    )


@router.post("/returns/{case_id}/reject")
def returns_reject(
    case_id: uuid.UUID,
    body: RejectRequest,
    context: Annotated[TenantContext, Depends(tenant_context)],
    db: Annotated[Session, Depends(get_session)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, Any]:
    payload = {"case_id": str(case_id), **body.model_dump()}
    return _idem(
        db,
        context=context,
        key=idempotency_key,
        scope=f"return.reject:{case_id}",
        payload=payload,
        operation=lambda: case_view(
            reject_case(
                db,
                context=context,
                case_id=case_id,
                expected_version=body.expected_version,
                reason=body.reason,
            )
        ),
    )


@router.post("/returns/{case_id}/provider-reconcile")
def returns_provider_reconcile(
    case_id: uuid.UUID,
    context: Annotated[TenantContext, Depends(tenant_context)],
    db: Annotated[Session, Depends(get_session)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, Any]:
    payload = {"case_id": str(case_id)}
    return _idem(
        db,
        context=context,
        key=idempotency_key,
        scope=f"return.provider_reconcile:{case_id}",
        payload=payload,
        operation=lambda: reconcile_unknown_refund(
            db,
            context=context,
            case_id=case_id,
            provider=PaymentProviderClient(),
        ),
    )


@router.post("/returns/{case_id}/retry-failed-refund")
def returns_retry_failed_refund(
    case_id: uuid.UUID,
    body: VersionedAction,
    context: Annotated[TenantContext, Depends(tenant_context)],
    db: Annotated[Session, Depends(get_session)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, Any]:
    payload = {"case_id": str(case_id), **body.model_dump()}
    return _idem(
        db,
        context=context,
        key=idempotency_key,
        scope=f"return.retry_failed_refund:{case_id}",
        payload=payload,
        operation=lambda: case_view(
            retry_failed_refund(
                db,
                context=context,
                case_id=case_id,
                expected_version=body.expected_version,
            )
        ),
    )


@router.post("/returns/{case_id}/mark-reconciled")
def returns_mark_reconciled(
    case_id: uuid.UUID,
    body: VersionedAction,
    context: Annotated[TenantContext, Depends(tenant_context)],
    db: Annotated[Session, Depends(get_session)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, Any]:
    payload = {"case_id": str(case_id), **body.model_dump()}
    return _idem(
        db,
        context=context,
        key=idempotency_key,
        scope=f"return.mark_reconciled:{case_id}",
        payload=payload,
        operation=lambda: case_view(
            reconcile_case(
                db,
                context=context,
                case_id=case_id,
                expected_version=body.expected_version,
            )
        ),
    )


@router.post("/returns/{case_id}/close")
def returns_close(
    case_id: uuid.UUID,
    body: VersionedAction,
    context: Annotated[TenantContext, Depends(tenant_context)],
    db: Annotated[Session, Depends(get_session)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, Any]:
    payload = {"case_id": str(case_id), **body.model_dump()}
    return _idem(
        db,
        context=context,
        key=idempotency_key,
        scope=f"return.close:{case_id}",
        payload=payload,
        operation=lambda: case_view(
            close_case(
                db,
                context=context,
                case_id=case_id,
                expected_version=body.expected_version,
            )
        ),
    )


@router.post("/webhooks/payment")
def payment_webhook(
    payload: dict[str, Any],
    db: Annotated[Session, Depends(get_session)],
    webhook_secret: Annotated[str | None, Header(alias="X-Webhook-Secret")] = None,
) -> dict[str, Any]:
    if webhook_secret is None or not secure_equal(
        webhook_secret, get_settings().payment_webhook_secret
    ):
        raise PermissionDenied("invalid webhook secret")
    return process_payment_webhook(db, payload=payload)
