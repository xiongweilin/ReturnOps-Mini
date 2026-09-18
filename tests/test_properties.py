from __future__ import annotations

import uuid

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select

from returnops.domain.states import (
    ROLE_BY_TARGET,
    SYSTEM_TARGETS,
    TRANSITIONS,
    RefundAttemptStatus,
    ReturnStatus,
    Role,
    assert_actor_can_transition,
    assert_approved_amount,
    assert_transition,
)
from returnops.errors import Conflict, InvalidTransition, PermissionDenied, ValidationFailure
from returnops.models import RefundAttempt, ReturnCase, WebhookReceipt
from returnops.services.payments import mark_dispatching, mark_unknown
from returnops.services.refunds import retry_failed_refund
from returnops.services.webhooks import _payload_hash, process_payment_webhook

from .helpers import create_pending_refund

ALL_STATUSES = list(ReturnStatus)
ALL_ROLES = list(Role)
TERMINAL_STATUSES = [status for status in ALL_STATUSES if not TRANSITIONS[status]]
HUMAN_TARGETS = [status for status in ALL_STATUSES if status not in SYSTEM_TARGETS]

DB_SETTINGS = settings(
    max_examples=6,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


@given(current=st.sampled_from(ALL_STATUSES), target=st.sampled_from(ALL_STATUSES))
def test_transition_table_is_total_and_exclusive(
    current: ReturnStatus, target: ReturnStatus
) -> None:
    """任意状态对只有两种结果：声明过的转换通过，未声明的转换必然被拒绝。"""
    if target in TRANSITIONS[current]:
        assert_transition(current, target)
    else:
        with pytest.raises(InvalidTransition):
            assert_transition(current, target)


@given(current=st.sampled_from(TERMINAL_STATUSES), target=st.sampled_from(ALL_STATUSES))
def test_terminal_statuses_never_move(current: ReturnStatus, target: ReturnStatus) -> None:
    """终态对任何目标都不可再转换，包括它自己。"""
    with pytest.raises(InvalidTransition):
        assert_transition(current, target)


@given(role=st.sampled_from(ALL_ROLES), target=st.sampled_from(sorted(SYSTEM_TARGETS, key=str)))
def test_system_targets_reject_every_human_role(role: Role, target: ReturnStatus) -> None:
    """系统拥有的目标不能由任何人类角色直接写入，只有 system=True 通道可以。"""
    with pytest.raises(PermissionDenied):
        assert_actor_can_transition(role, target)
    assert_actor_can_transition(role, target, system=True)


@given(
    role=st.sampled_from(ALL_ROLES),
    target=st.sampled_from(HUMAN_TARGETS),
)
def test_role_gate_matches_declared_table(role: Role, target: ReturnStatus) -> None:
    """人类目标的角色门与声明表一致，不存在"表里允许但代码拒绝"或反之。"""
    allowed = ROLE_BY_TARGET.get(target)
    if allowed is None or role in allowed:
        assert_actor_can_transition(role, target)
    else:
        with pytest.raises(PermissionDenied):
            assert_actor_can_transition(role, target)


@given(
    requested=st.integers(min_value=0, max_value=10**9),
    approved=st.integers(min_value=-(10**3), max_value=10**9),
)
def test_approved_amount_rule_is_total(requested: int, approved: int) -> None:
    """金额规则：只有 0 < approved <= requested 才通过，其余全部拒绝。"""
    if 0 < approved <= requested:
        assert_approved_amount(requested, approved)
    else:
        with pytest.raises(ValidationFailure):
            assert_approved_amount(requested, approved)


@given(payload=st.dictionaries(st.text(min_size=1, max_size=6), st.integers(), max_size=5))
def test_payload_hash_ignores_key_order(payload: dict[str, int]) -> None:
    """Webhook 去重依赖规范化哈希：键顺序不同但内容相同必须得到同一个指纹。"""
    reordered = dict(reversed(list(payload.items())))
    assert _payload_hash(payload) == _payload_hash(reordered)


@DB_SETTINGS
@given(deliveries=st.integers(min_value=1, max_value=5))
def test_repeated_webhook_delivery_advances_state_at_most_once(db, seeded, deliveries: int) -> None:
    """同一 event_id 重复投递任意次：只落一条回执、只推进一次状态、只成功一次。"""
    case = create_pending_refund(db, seeded)
    attempt = db.execute(
        select(RefundAttempt).where(RefundAttempt.return_case_id == case.id)
    ).scalar_one()
    event_id = f"evt-{uuid.uuid4().hex}"
    payload = {
        "event_id": event_id,
        "refund_id": f"rf-{uuid.uuid4().hex}",
        "idempotency_key": attempt.provider_idempotency_key,
        "status": "succeeded",
        "amount_minor": attempt.amount_minor,
        "currency": attempt.currency,
    }

    results = [process_payment_webhook(db, payload=payload) for _ in range(deliveries)]

    assert results[0] == {"accepted": True, "replayed": False}
    assert all(result == {"accepted": True, "replayed": True} for result in results[1:])
    receipts = (
        db.execute(select(WebhookReceipt).where(WebhookReceipt.event_id == event_id))
        .scalars()
        .all()
    )
    assert len(receipts) == 1
    assert db.get(ReturnCase, case.id).status is ReturnStatus.REFUNDED
    assert attempt.status is RefundAttemptStatus.SUCCEEDED


@DB_SETTINGS
@given(reason=st.text(min_size=1, max_size=24))
def test_unknown_outcome_never_triggers_a_second_refund(db, seeded, reason: str) -> None:
    """结果未知只能通过对账收敛：不得重试派发，也不得产生第二个退款意图。"""
    case = create_pending_refund(db, seeded)
    attempt = db.execute(
        select(RefundAttempt).where(RefundAttempt.return_case_id == case.id)
    ).scalar_one()

    mark_dispatching(db, attempt)
    mark_unknown(db, attempt, error=reason)
    db.flush()
    refreshed = db.get(ReturnCase, case.id)
    assert refreshed is not None
    assert refreshed.status is ReturnStatus.REFUND_UNKNOWN
    assert attempt.status is RefundAttemptStatus.UNKNOWN

    finance = seeded.contexts[Role.FINANCE][0]
    with pytest.raises(Conflict):
        retry_failed_refund(
            db,
            context=finance,
            case_id=case.id,
            expected_version=refreshed.version,
        )

    attempts = (
        db.execute(select(RefundAttempt).where(RefundAttempt.return_case_id == case.id))
        .scalars()
        .all()
    )
    assert len(attempts) == 1
    assert attempts[0].provider_idempotency_key == attempt.provider_idempotency_key


@DB_SETTINGS
# 高额阈值以上需要第二个审批人，属于另一条规则；这里只取单审批可完成的金额区间。
@given(amount=st.integers(min_value=1, max_value=49_999))
def test_reused_event_id_with_a_different_body_always_conflicts(db, seeded, amount: int) -> None:
    """同一个 event_id 携带不同内容时必须是冲突，不能当成重放被静默吞掉。"""
    case = create_pending_refund(db, seeded, amount=amount)
    attempt = db.execute(
        select(RefundAttempt).where(RefundAttempt.return_case_id == case.id)
    ).scalar_one()
    event_id = f"evt-{uuid.uuid4().hex}"
    base = {
        "event_id": event_id,
        "refund_id": f"rf-{uuid.uuid4().hex}",
        "idempotency_key": attempt.provider_idempotency_key,
        "status": "succeeded",
        "amount_minor": attempt.amount_minor,
        "currency": attempt.currency,
    }
    process_payment_webhook(db, payload=base)

    changed = {**base, "refund_id": f"rf-{uuid.uuid4().hex}"}
    with pytest.raises(Conflict):
        process_payment_webhook(db, payload=changed)
