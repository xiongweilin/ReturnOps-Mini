from __future__ import annotations

import pytest

from returnops.domain.states import (
    ReturnStatus,
    Role,
    assert_actor_can_transition,
    assert_transition,
)
from returnops.errors import InvalidTransition, PermissionDenied


def test_declared_happy_path_is_legal() -> None:
    path = [
        ReturnStatus.REQUESTED,
        ReturnStatus.AUTHORIZED,
        ReturnStatus.RECEIVED,
        ReturnStatus.INSPECTED,
        ReturnStatus.REFUND_APPROVED,
        ReturnStatus.REFUND_PENDING,
        ReturnStatus.REFUNDED,
        ReturnStatus.RECONCILED,
        ReturnStatus.CLOSED,
    ]
    for current, target in zip(path, path[1:]):
        assert_transition(current, target)


def test_closed_is_terminal() -> None:
    with pytest.raises(InvalidTransition):
        assert_transition(ReturnStatus.CLOSED, ReturnStatus.REQUESTED)


def test_unknown_outcome_cannot_jump_back_to_pending() -> None:
    with pytest.raises(InvalidTransition):
        assert_transition(ReturnStatus.REFUND_UNKNOWN, ReturnStatus.REFUND_PENDING)


def test_failed_reconciliation_can_return_to_pending_only_from_needs_reconciliation() -> None:
    assert_transition(ReturnStatus.NEEDS_RECONCILIATION, ReturnStatus.REFUND_PENDING)


def test_human_cannot_mark_refunded() -> None:
    with pytest.raises(PermissionDenied):
        assert_actor_can_transition(Role.ADMIN, ReturnStatus.REFUNDED, system=False)


def test_system_cannot_take_human_approval_transition() -> None:
    with pytest.raises(PermissionDenied):
        assert_actor_can_transition(None, ReturnStatus.AUTHORIZED, system=True)
