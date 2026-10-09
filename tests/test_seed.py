from __future__ import annotations

from sqlalchemy import func, select

from returnops.domain.states import Role
from returnops.models import IdempotencyRecord, ReturnCase
from returnops.seed import INTAKE_EVENT_ID, INTAKE_PAYLOAD, _ensure_intake_sample


def test_seeded_intake_case_is_repeatable_and_replays_the_same_event(db, seeded) -> None:
    customer_service = seeded.contexts[Role.CUSTOMER_SERVICE][0]
    _ensure_intake_sample(db, seeded.organization.id, customer_service)
    _ensure_intake_sample(db, seeded.organization.id, customer_service)

    case = db.execute(
        select(ReturnCase).where(
            ReturnCase.organization_id == seeded.organization.id,
            ReturnCase.external_order_ref == INTAKE_PAYLOAD["external_order_ref"],
        )
    ).scalar_one()
    case_count = db.execute(
        select(func.count())
        .select_from(ReturnCase)
        .where(
            ReturnCase.organization_id == seeded.organization.id,
            ReturnCase.external_order_ref == INTAKE_PAYLOAD["external_order_ref"],
        )
    ).scalar_one()
    replay = db.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.organization_id == seeded.organization.id,
            IdempotencyRecord.scope == "return.create",
            IdempotencyRecord.key == f"return-intake:{INTAKE_EVENT_ID}",
        )
    ).scalar_one()

    assert case_count == 1
    assert replay.response_json is not None
    assert replay.response_json["id"] == str(case.id)
