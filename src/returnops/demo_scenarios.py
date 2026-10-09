from __future__ import annotations

import argparse
import re
import uuid

from sqlalchemy import select

from returnops.config import get_settings
from returnops.db import SessionLocal
from returnops.domain.states import RefundAttemptStatus, ReturnStatus, Role
from returnops.errors import Conflict, NotFound
from returnops.models import Membership, Organization, OutboxEvent, RefundAttempt, ReturnCase, User
from returnops.services.case_store import create_case
from returnops.services.outbox import TOPIC_REFUND_DISPATCH
from returnops.services.payments import PaymentProviderClient
from returnops.services.returns import (
    approve_refund,
    authorize_case,
    inspect_case,
    receive_case,
)
from returnops.services.tenancy import TenantContext
from returnops.services.worker import process_event_once

UNKNOWN_ORDER_REF = "DEMO-ORDER-UNKNOWN-001"
UNKNOWN_ORDER_REF_PATTERN = re.compile(r"^DEMO-ORDER-UNKNOWN-[0-9]{3}$")


def _context(db, organization_id: uuid.UUID, role: Role, *, index: int = 0) -> TenantContext:
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
        raise NotFound(f"demo identity for {role.value} slot {index} is not initialized")
    return TenantContext(organization_id, users[index].id, role)


def prepare_unknown_refund(
    external_order_ref: str = UNKNOWN_ORDER_REF,
) -> tuple[uuid.UUID, uuid.UUID]:
    if UNKNOWN_ORDER_REF_PATTERN.fullmatch(external_order_ref) is None:
        raise Conflict("demo order reference must match DEMO-ORDER-UNKNOWN-NNN")
    settings = get_settings()
    if not (settings.demo_mode and settings.environment == "demo"):
        raise Conflict("unknown-result injection is available only in the local demo environment")
    if settings.high_value_threshold < 2:
        raise Conflict("high-value threshold must be at least two minor units for demo data")

    with SessionLocal() as db:
        organization = db.execute(
            select(Organization).where(Organization.name == settings.demo_organization_name)
        ).scalar_one_or_none()
        if organization is None:
            raise NotFound("demo organization is not initialized; run the demo seed first")
        existing = db.execute(
            select(ReturnCase).where(
                ReturnCase.organization_id == organization.id,
                ReturnCase.external_order_ref == external_order_ref,
            )
        ).scalar_one_or_none()
        if existing is None:
            customer_service = _context(db, organization.id, Role.CUSTOMER_SERVICE)
            warehouse = _context(db, organization.id, Role.WAREHOUSE)
            finance = _context(db, organization.id, Role.FINANCE)
            case = create_case(
                db,
                context=customer_service,
                external_order_ref=external_order_ref,
                customer_ref=f"DEMO-CUSTOMER-{external_order_ref.rsplit('-', maxsplit=1)[-1]}",
                reason="演示异常：支付方已处理退款，但确认响应丢失。",
                requested_amount_minor=min(19900, settings.high_value_threshold - 1),
                currency="CNY",
            )
            case = authorize_case(
                db,
                context=customer_service,
                case_id=case.id,
                expected_version=case.version,
                rationale="演示流程：资格审核通过。",
            )
            case = receive_case(
                db,
                context=warehouse,
                case_id=case.id,
                expected_version=case.version,
            )
            case = inspect_case(
                db,
                context=warehouse,
                case_id=case.id,
                expected_version=case.version,
                notes="演示验货通过。",
            )
            case, second_approval_required = approve_refund(
                db,
                context=finance,
                case_id=case.id,
                expected_version=case.version,
                approved_amount_minor=case.requested_amount_minor,
                rationale="演示流程：财务已批准退款。",
            )
            if second_approval_required:
                raise Conflict("unknown-result sample unexpectedly requires a second approver")
        else:
            case = existing
            if case.status is not ReturnStatus.REFUND_PENDING:
                attempt = db.execute(
                    select(RefundAttempt).where(RefundAttempt.return_case_id == case.id)
                ).scalar_one_or_none()
                if case.status is ReturnStatus.REFUND_UNKNOWN and attempt is not None:
                    return case.id, uuid.UUID(
                        db.execute(
                            select(OutboxEvent.aggregate_id).where(
                                OutboxEvent.organization_id == organization.id,
                                OutboxEvent.topic == TOPIC_REFUND_DISPATCH,
                                OutboxEvent.aggregate_type == "refund_attempt",
                                OutboxEvent.aggregate_id == str(attempt.id),
                            )
                        ).scalar_one()
                    )
                raise Conflict(
                    f"existing unknown-result sample is in {case.status.value}; "
                    "reconcile or reset the demo before creating another refund"
                )

        attempt = db.execute(
            select(RefundAttempt).where(RefundAttempt.return_case_id == case.id)
        ).scalar_one_or_none()
        if attempt is None:
            raise Conflict("approved demo case has no refund intent")
        if attempt.status is RefundAttemptStatus.UNKNOWN:
            raise Conflict("refund result is already unknown; do not dispatch it again")
        if attempt.status is not RefundAttemptStatus.PLANNED:
            raise Conflict(f"refund intent is {attempt.status.value}, expected planned")

        event = db.execute(
            select(OutboxEvent).where(
                OutboxEvent.organization_id == organization.id,
                OutboxEvent.topic == TOPIC_REFUND_DISPATCH,
                OutboxEvent.aggregate_type == "refund_attempt",
                OutboxEvent.aggregate_id == str(attempt.id),
            )
        ).scalar_one_or_none()
        if event is None:
            raise Conflict("approved demo case has no refund dispatch event")
        case_id = case.id
        event_id = event.id
        db.commit()
        return case_id, event_id


def run_unknown_result_demo(external_order_ref: str = UNKNOWN_ORDER_REF) -> None:
    case_id, event_id = prepare_unknown_refund(external_order_ref)
    processed = process_event_once(
        event_id,
        provider=PaymentProviderClient(simulation_mode="timeout_after_processing_no_webhook"),
    )
    if not processed:
        with SessionLocal() as db:
            case = db.get(ReturnCase, case_id)
            attempt = db.execute(
                select(RefundAttempt).where(RefundAttempt.return_case_id == case_id)
            ).scalar_one()
            if (
                case is not None
                and case.status is ReturnStatus.REFUND_UNKNOWN
                and attempt.status is RefundAttemptStatus.UNKNOWN
            ):
                print(f"case_id={case.id}")
                print(f"case_ref={case.case_ref}")
                print(f"case_status={case.status.value}")
                print(f"refund_attempt_status={attempt.status.value}")
                print("This case is already UNKNOWN; no additional payment dispatch was attempted.")
                return
        raise Conflict("refund event could not be claimed; the worker may already be processing it")

    with SessionLocal() as db:
        case = db.get(ReturnCase, case_id)
        attempt = db.execute(
            select(RefundAttempt).where(RefundAttempt.return_case_id == case_id)
        ).scalar_one()
        if case is None:
            raise NotFound("unknown-result demo case disappeared")
        if (
            case.status is not ReturnStatus.REFUND_UNKNOWN
            or attempt.status is not RefundAttemptStatus.UNKNOWN
        ):
            raise Conflict(
                f"fault demo ended at case={case.status.value}, refund={attempt.status.value}; "
                "inspect the worker and Fake Payment execution"
            )
        print(f"case_id={case.id}")
        print(f"case_ref={case.case_ref}")
        print(f"case_status={case.status.value}")
        print(f"refund_attempt_status={attempt.status.value}")
        print(
            "The provider stored the refund and no Webhook was delivered; query provider state in the UI."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run one local-only unknown-result demonstration.")
    parser.add_argument("--order-ref", default=UNKNOWN_ORDER_REF)
    args = parser.parse_args()
    run_unknown_result_demo(args.order_ref)
