from __future__ import annotations

from sqlalchemy.orm import Session

from returnops.domain.states import Role
from returnops.services.returns import (
    approve_refund,
    authorize_case,
    create_case,
    inspect_case,
    receive_case,
)


def create_inspected_case(db: Session, seeded, *, requested_amount: int = 1000):
    service = seeded.contexts[Role.CUSTOMER_SERVICE][0]
    warehouse = seeded.contexts[Role.WAREHOUSE][0]
    case = create_case(
        db,
        context=service,
        external_order_ref="ORDER-1",
        customer_ref="CUSTOMER-1",
        reason="damaged",
        requested_amount_minor=requested_amount,
        currency="USD",
    )
    case = authorize_case(
        db,
        context=service,
        case_id=case.id,
        expected_version=case.version,
        rationale="eligible",
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
        notes="item inspected",
    )
    return case


def create_pending_refund(db: Session, seeded, *, amount: int = 1000):
    case = create_inspected_case(db, seeded, requested_amount=amount)
    finance = seeded.contexts[Role.FINANCE][0]
    case, second = approve_refund(
        db,
        context=finance,
        case_id=case.id,
        expected_version=case.version,
        approved_amount_minor=amount,
        rationale="refund approved",
    )
    assert second is False
    return case
