from __future__ import annotations

import time
from pathlib import Path
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from returnops.config import get_settings
from returnops.db import SessionLocal
from returnops.domain.states import ApprovalKind, ReturnStatus, Role
from returnops.models import Approval, Membership, Organization, ReturnCase, User
from returnops.security import hash_token, issue_token
from returnops.services.case_store import case_view
from returnops.services.idempotency import claim, complete
from returnops.services.returns import (
    approve_refund,
    authorize_case,
    close_case,
    create_case,
    inspect_case,
    receive_case,
    reconcile_case,
    reject_case,
)
from returnops.services.tenancy import TenantContext

DEMO_USERS = (
    ("service@example.test", "Customer Service", Role.CUSTOMER_SERVICE),
    ("warehouse@example.test", "Warehouse", Role.WAREHOUSE),
    ("finance-a@example.test", "Finance A", Role.FINANCE),
    ("finance-b@example.test", "Finance B", Role.FINANCE),
    ("admin@example.test", "Administrator", Role.ADMIN),
    ("automation@example.test", "ReturnFlow Automation", Role.AUTOMATION),
)

INTAKE_EVENT_ID = "demo-return-001"


class IntakePayload(TypedDict):
    external_order_ref: str
    customer_ref: str
    reason: str
    requested_amount_minor: int
    currency: str


INTAKE_PAYLOAD: IntakePayload = {
    "external_order_ref": "DEMO-ORDER-INTAKE-001",
    "customer_ref": "DEMO-CUSTOMER-001",
    "reason": "商品尺寸不合适",
    "requested_amount_minor": 12900,
    "currency": "CNY",
}


def _context(db: Session, organization_id, role: Role, *, index: int = 0) -> TenantContext:
    users = list(
        db.execute(
            select(User)
            .join(Membership, Membership.user_id == User.id)
            .where(
                Membership.organization_id == organization_id,
                Membership.role == role,
                User.is_active.is_(True),
            )
            .order_by(User.email)
        )
        .scalars()
        .all()
    )
    if index >= len(users):
        raise RuntimeError(f"demo identity for {role.value} slot {index} is missing")
    return TenantContext(organization_id, users[index].id, role)


def _find_case(db: Session, organization_id, external_order_ref: str) -> ReturnCase | None:
    return db.execute(
        select(ReturnCase).where(
            ReturnCase.organization_id == organization_id,
            ReturnCase.external_order_ref == external_order_ref,
        )
    ).scalar_one_or_none()


def _new_case(
    db: Session,
    *,
    organization_id,
    context: TenantContext,
    external_order_ref: str,
    customer_ref: str,
    reason: str,
    requested_amount_minor: int,
) -> ReturnCase:
    existing = _find_case(db, organization_id, external_order_ref)
    if existing is not None:
        return existing
    return create_case(
        db,
        context=context,
        external_order_ref=external_order_ref,
        customer_ref=customer_ref,
        reason=reason,
        requested_amount_minor=requested_amount_minor,
        currency="CNY",
    )


def _advance_to_inspected(
    db: Session,
    *,
    case: ReturnCase,
    customer_service: TenantContext,
    warehouse: TenantContext,
) -> ReturnCase:
    if case.status is ReturnStatus.REQUESTED:
        case = authorize_case(
            db,
            context=customer_service,
            case_id=case.id,
            expected_version=case.version,
            rationale="演示样本：退货资格通过",
        )
    if case.status is ReturnStatus.AUTHORIZED:
        case = receive_case(
            db,
            context=warehouse,
            case_id=case.id,
            expected_version=case.version,
        )
    if case.status is ReturnStatus.RECEIVED:
        case = inspect_case(
            db,
            context=warehouse,
            case_id=case.id,
            expected_version=case.version,
            notes="演示验货：商品已收回并完成外观检查。",
        )
    return case


def _ensure_intake_sample(db: Session, organization_id, customer_service: TenantContext) -> None:
    key = f"return-intake:{INTAKE_EVENT_ID}"
    claimed = claim(
        db,
        organization_id=organization_id,
        scope="return.create",
        key=key,
        request_payload=INTAKE_PAYLOAD,
    )
    if claimed.replay is not None:
        return
    case = _find_case(db, organization_id, INTAKE_PAYLOAD["external_order_ref"])
    if case is None:
        case = create_case(db, context=customer_service, **INTAKE_PAYLOAD)
    complete(claimed, case_view(case))


def _ensure_rejected_sample(db: Session, organization_id, customer_service: TenantContext) -> None:
    case = _new_case(
        db,
        organization_id=organization_id,
        context=customer_service,
        external_order_ref="DEMO-ORDER-REJECTED-001",
        customer_ref="DEMO-CUSTOMER-002",
        reason="演示样本：超过商户设置的退货期限。",
        requested_amount_minor=8900,
    )
    if case.status is ReturnStatus.REQUESTED:
        reject_case(
            db,
            context=customer_service,
            case_id=case.id,
            expected_version=case.version,
            reason="演示拒绝路径：申请不符合退货期限要求。",
        )


def _ensure_warehouse_sample(
    db: Session,
    organization_id,
    customer_service: TenantContext,
    warehouse: TenantContext,
) -> None:
    case = _new_case(
        db,
        organization_id=organization_id,
        context=customer_service,
        external_order_ref="DEMO-ORDER-WAREHOUSE-001",
        customer_ref="DEMO-CUSTOMER-003",
        reason="演示样本：等待仓库检查退回商品。",
        requested_amount_minor=15900,
    )
    if case.status in {ReturnStatus.REQUESTED, ReturnStatus.AUTHORIZED}:
        if case.status is ReturnStatus.REQUESTED:
            case = authorize_case(
                db,
                context=customer_service,
                case_id=case.id,
                expected_version=case.version,
                rationale="演示样本：退货资格通过",
            )
        receive_case(
            db,
            context=warehouse,
            case_id=case.id,
            expected_version=case.version,
        )


def _ensure_finance_sample(
    db: Session,
    organization_id,
    customer_service: TenantContext,
    warehouse: TenantContext,
) -> None:
    case = _new_case(
        db,
        organization_id=organization_id,
        context=customer_service,
        external_order_ref="DEMO-ORDER-FINANCE-001",
        customer_ref="DEMO-CUSTOMER-004",
        reason="演示样本：验货完成，等待财务审批。",
        requested_amount_minor=22300,
    )
    _advance_to_inspected(
        db,
        case=case,
        customer_service=customer_service,
        warehouse=warehouse,
    )


def _ensure_high_value_sample(
    db: Session,
    organization_id,
    customer_service: TenantContext,
    warehouse: TenantContext,
    finance_a: TenantContext,
) -> None:
    threshold = get_settings().high_value_threshold
    if threshold < 2 or threshold > 100_000_000:
        raise ValueError("high-value threshold must be between 2 and 100,000,000 minor units")
    amount = max(threshold, 60000)
    if amount > 100_000_000:
        raise ValueError("high-value threshold must be below the ReturnCreate maximum")

    case = _new_case(
        db,
        organization_id=organization_id,
        context=customer_service,
        external_order_ref="DEMO-ORDER-HIGH-VALUE-001",
        customer_ref="DEMO-CUSTOMER-005",
        reason="演示样本：退款金额达到配置的双人审批阈值。",
        requested_amount_minor=min(amount + 1000, 100_000_000),
    )
    case = _advance_to_inspected(
        db,
        case=case,
        customer_service=customer_service,
        warehouse=warehouse,
    )
    if case.status is ReturnStatus.INSPECTED:
        existing_approval = db.execute(
            select(Approval).where(
                Approval.organization_id == organization_id,
                Approval.return_case_id == case.id,
                Approval.kind == ApprovalKind.REFUND,
            )
        ).scalar_one_or_none()
        if existing_approval is None:
            _case, second_approval_required = approve_refund(
                db,
                context=finance_a,
                case_id=case.id,
                expected_version=case.version,
                approved_amount_minor=amount,
                rationale="演示高额退款：第一位财务审批人。",
            )
            if not second_approval_required:
                raise RuntimeError("configured high-value sample did not require a second approver")


def _ensure_normal_closed_sample(
    db: Session,
    organization_id,
    customer_service: TenantContext,
    warehouse: TenantContext,
    finance_a: TenantContext,
) -> str:
    threshold = get_settings().high_value_threshold
    amount = min(12900, threshold - 1) if threshold > 1 else 1
    case = _new_case(
        db,
        organization_id=organization_id,
        context=customer_service,
        external_order_ref="DEMO-ORDER-CLOSED-001",
        customer_ref="DEMO-CUSTOMER-006",
        reason="演示样本：完整通过审批、退款和结案。",
        requested_amount_minor=amount,
    )
    case = _advance_to_inspected(
        db,
        case=case,
        customer_service=customer_service,
        warehouse=warehouse,
    )
    if case.status is ReturnStatus.INSPECTED:
        case, second_approval_required = approve_refund(
            db,
            context=finance_a,
            case_id=case.id,
            expected_version=case.version,
            approved_amount_minor=amount,
            rationale="演示样本：低于当前双人审批阈值。",
        )
        if second_approval_required:
            raise RuntimeError("normal sample unexpectedly requires a second approver")
    return "DEMO-ORDER-CLOSED-001"


def _finish_normal_sample(external_order_ref: str, organization_id) -> None:
    for _attempt in range(60):
        with SessionLocal() as db:
            case = _find_case(db, organization_id, external_order_ref)
            if case is None:
                return
            if case.status in {ReturnStatus.REFUND_UNKNOWN, ReturnStatus.NEEDS_RECONCILIATION}:
                print(f"normal sample remains in exception state: {case.status.value}")
                return
            if case.status is ReturnStatus.REFUNDED:
                finance = _context(db, organization_id, Role.FINANCE)
                case = reconcile_case(
                    db,
                    context=finance,
                    case_id=case.id,
                    expected_version=case.version,
                )
                close_case(
                    db,
                    context=finance,
                    case_id=case.id,
                    expected_version=case.version,
                )
                db.commit()
                print("normal refund sample reached closed status")
                return
            if case.status is ReturnStatus.RECONCILED:
                finance = _context(db, organization_id, Role.FINANCE)
                close_case(
                    db,
                    context=finance,
                    case_id=case.id,
                    expected_version=case.version,
                )
                db.commit()
                print("normal refund sample reached closed status")
                return
            if case.status in {ReturnStatus.CLOSED, ReturnStatus.REJECTED}:
                return
        time.sleep(0.5)
    print("normal refund sample is still processing; inspect its current state in ReturnFlow")


def _initialize_automation_token_file(
    *, generated_token: str | None, path: Path, db: Session, organization: Organization
) -> None:
    if generated_token is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(generated_token + "\n", encoding="utf-8")
        return
    if path.exists():
        return

    automation = db.execute(
        select(User)
        .join(Membership, Membership.user_id == User.id)
        .where(
            User.email == "automation@example.test",
            Membership.organization_id == organization.id,
            Membership.role == Role.AUTOMATION,
        )
    ).scalar_one()
    rotated_token = issue_token()
    automation.api_token_hash = hash_token(rotated_token)
    db.flush()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rotated_token + "\n", encoding="utf-8")
    db.commit()


def main() -> None:
    settings = get_settings()
    automation_token_path = Path(settings.demo_automation_token_file)
    generated_automation_token: str | None = None
    with SessionLocal() as db:
        organization = db.execute(
            select(Organization).where(Organization.name == settings.demo_organization_name)
        ).scalar_one_or_none()
        if organization is None:
            organization = Organization(name=settings.demo_organization_name)
            db.add(organization)
            db.flush()

        for email, display_name, role in DEMO_USERS:
            user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
            if user is None:
                token = issue_token()
                user = User(
                    email=email,
                    display_name=display_name,
                    api_token_hash=hash_token(token),
                )
                db.add(user)
                db.flush()
                if role is Role.AUTOMATION:
                    generated_automation_token = token

            membership = db.execute(
                select(Membership).where(
                    Membership.organization_id == organization.id,
                    Membership.user_id == user.id,
                )
            ).scalar_one_or_none()
            if membership is None:
                db.add(Membership(organization_id=organization.id, user_id=user.id, role=role))
            elif membership.role is not role:
                membership.role = role

        db.flush()
        customer_service = _context(db, organization.id, Role.CUSTOMER_SERVICE)
        warehouse = _context(db, organization.id, Role.WAREHOUSE)
        finance_a = _context(db, organization.id, Role.FINANCE)

        _ensure_intake_sample(db, organization.id, customer_service)
        _ensure_rejected_sample(db, organization.id, customer_service)
        _ensure_warehouse_sample(db, organization.id, customer_service, warehouse)
        _ensure_finance_sample(db, organization.id, customer_service, warehouse)
        _ensure_high_value_sample(db, organization.id, customer_service, warehouse, finance_a)

        normal_order_ref: str | None = None
        if settings.payment_simulation_mode == "normal":
            normal_order_ref = _ensure_normal_closed_sample(
                db,
                organization.id,
                customer_service,
                warehouse,
                finance_a,
            )
        else:
            print("normal refund sample not queued because payment simulation mode is not normal")

        organization_id = organization.id
        db.commit()
        _initialize_automation_token_file(
            generated_token=generated_automation_token,
            path=automation_token_path,
            db=db,
            organization=organization,
        )
        db.commit()

    if normal_order_ref is not None:
        _finish_normal_sample(normal_order_ref, organization_id)

    print(f"organization_id={organization_id}")
    print("fictional demo identities and repeatable sample cases are ready")
    print(f"automation credential file: {automation_token_path}")


if __name__ == "__main__":
    main()
