from __future__ import annotations

import uuid
from typing import Annotated, Any, Callable

from fastapi import APIRouter, Cookie, Depends, Header, Query, Response
from sqlalchemy.orm import Session

from returnops.config import get_settings
from returnops.db import get_session
from returnops.domain.states import ReturnStatus, Role
from returnops.errors import AuthenticationError, PermissionDenied
from returnops.schemas import (
    ApproveRefundRequest,
    AuthorizeRequest,
    DemoSessionRequest,
    InspectRequest,
    RejectRequest,
    ReturnCreate,
    VersionedAction,
)
from returnops.models import User
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
from returnops.services.case_store import count_cases
from returnops.services.demo_auth import (
    DEMO_SESSION_COOKIE,
    demo_mode_enabled,
    issue_demo_session,
    resolve_demo_session,
    revoke_demo_session,
)
from returnops.services.operator_queries import case_detail_view, exception_cases, overview
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


@router.get("/me")
def current_identity(
    context: Annotated[TenantContext, Depends(tenant_context)],
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, str]:
    user = db.get(User, context.user_id)
    if user is None:
        raise AuthenticationError("user is no longer available")
    return {
        "organizationId": str(context.organization_id),
        "userId": str(user.id),
        "displayName": user.display_name,
        "role": context.role.value,
    }


@router.get("/returns")
def returns_list(
    context: Annotated[TenantContext, Depends(tenant_context)],
    db: Annotated[Session, Depends(get_session)],
    status: ReturnStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    q: str | None = Query(default=None, max_length=200),
) -> dict[str, Any]:
    return {
        "items": [
            case_view(row)
            for row in list_cases(
                db, context=context, status=status, limit=limit, offset=offset, search=q
            )
        ],
        "total": count_cases(db, context=context, status=status, search=q),
        "limit": limit,
        "offset": offset,
    }


@router.get("/overview")
def returns_overview(
    context: Annotated[TenantContext, Depends(tenant_context)],
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    return overview(db, context=context)


@router.get("/returns/exceptions")
def returns_exceptions(
    context: Annotated[TenantContext, Depends(tenant_context)],
    db: Annotated[Session, Depends(get_session)],
    limit: int = Query(default=100, ge=1, le=200),
) -> dict[str, Any]:
    if context.role not in {Role.FINANCE, Role.ADMIN}:
        raise PermissionDenied("exception reconciliation is restricted to finance")
    return {
        "items": [
            case_detail_view(db, context=context, case=case)
            for case in exception_cases(db, context=context, limit=limit)
        ]
    }


@router.get("/returns/{case_id}")
def returns_get(
    case_id: uuid.UUID,
    context: Annotated[TenantContext, Depends(tenant_context)],
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    case = get_case(db, context=context, case_id=case_id)
    return case_detail_view(db, context=context, case=case)


@router.get("/demo/session")
def demo_session_status(
    db: Annotated[Session, Depends(get_session)],
    demo_session: Annotated[str | None, Cookie(alias=DEMO_SESSION_COOKIE)] = None,
) -> dict[str, Any]:
    if not demo_mode_enabled():
        return {"enabled": False, "authenticated": False}
    if not demo_session:
        return {"enabled": True, "authenticated": False}
    try:
        user, organization_id, role = resolve_demo_session(db, demo_session)
    except AuthenticationError:
        return {"enabled": True, "authenticated": False}
    return {
        "enabled": True,
        "authenticated": True,
        "organizationId": str(organization_id),
        "userId": str(user.id),
        "displayName": user.display_name,
        "role": role.value,
    }


@router.post("/demo/session")
def demo_session_create(
    body: DemoSessionRequest,
    response: Response,
    db: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    token, organization, user, max_age = issue_demo_session(
        db, role=body.role, finance_slot=body.finance_slot
    )
    response.set_cookie(
        key=DEMO_SESSION_COOKIE,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=False,
        samesite="strict",
        path="/",
    )
    _session_user, _session_org, role = resolve_demo_session(db, token)
    return {
        "enabled": True,
        "authenticated": True,
        "organizationId": str(organization.id),
        "userId": str(user.id),
        "displayName": user.display_name,
        "role": role.value,
    }


@router.delete("/demo/session")
def demo_session_delete(
    response: Response,
    demo_session: Annotated[str | None, Cookie(alias=DEMO_SESSION_COOKIE)] = None,
) -> dict[str, bool]:
    if demo_session:
        revoke_demo_session(demo_session)
    response.delete_cookie(
        key=DEMO_SESSION_COOKIE,
        httponly=True,
        secure=False,
        samesite="strict",
        path="/",
    )
    return {"authenticated": False}


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
