from __future__ import annotations

from enum import StrEnum

from returnops.errors import InvalidTransition, PermissionDenied, ValidationFailure


class Role(StrEnum):
    CUSTOMER_SERVICE = "customer_service"
    WAREHOUSE = "warehouse"
    FINANCE = "finance"
    ADMIN = "admin"


class ReturnStatus(StrEnum):
    REQUESTED = "requested"
    AUTHORIZED = "authorized"
    RECEIVED = "received"
    INSPECTED = "inspected"
    REFUND_APPROVED = "refund_approved"
    REFUND_PENDING = "refund_pending"
    REFUND_UNKNOWN = "refund_unknown"
    NEEDS_RECONCILIATION = "needs_reconciliation"
    REFUNDED = "refunded"
    RECONCILED = "reconciled"
    CLOSED = "closed"
    REJECTED = "rejected"


class RefundAttemptStatus(StrEnum):
    PLANNED = "planned"
    DISPATCHING = "dispatching"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ApprovalKind(StrEnum):
    ELIGIBILITY = "eligibility"
    REFUND = "refund"
    HIGH_VALUE_REFUND_SECOND = "high_value_refund_second"


class ApprovalDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


TRANSITIONS: dict[ReturnStatus, set[ReturnStatus]] = {
    ReturnStatus.REQUESTED: {ReturnStatus.AUTHORIZED, ReturnStatus.REJECTED},
    ReturnStatus.AUTHORIZED: {ReturnStatus.RECEIVED},
    ReturnStatus.RECEIVED: {ReturnStatus.INSPECTED},
    ReturnStatus.INSPECTED: {ReturnStatus.REFUND_APPROVED, ReturnStatus.REJECTED},
    ReturnStatus.REFUND_APPROVED: {ReturnStatus.REFUND_PENDING},
    ReturnStatus.REFUND_PENDING: {
        ReturnStatus.REFUNDED,
        ReturnStatus.REFUND_UNKNOWN,
        ReturnStatus.NEEDS_RECONCILIATION,
    },
    ReturnStatus.REFUND_UNKNOWN: {
        ReturnStatus.REFUNDED,
        ReturnStatus.NEEDS_RECONCILIATION,
    },
    ReturnStatus.NEEDS_RECONCILIATION: {ReturnStatus.REFUNDED, ReturnStatus.REFUND_PENDING},
    ReturnStatus.REFUNDED: {ReturnStatus.RECONCILED},
    ReturnStatus.RECONCILED: {ReturnStatus.CLOSED},
    ReturnStatus.CLOSED: set(),
    ReturnStatus.REJECTED: set(),
}

ROLE_BY_TARGET: dict[ReturnStatus, set[Role]] = {
    ReturnStatus.AUTHORIZED: {Role.CUSTOMER_SERVICE, Role.ADMIN},
    ReturnStatus.RECEIVED: {Role.WAREHOUSE, Role.ADMIN},
    ReturnStatus.INSPECTED: {Role.WAREHOUSE, Role.ADMIN},
    ReturnStatus.REFUND_APPROVED: {Role.FINANCE, Role.ADMIN},
    ReturnStatus.RECONCILED: {Role.FINANCE, Role.ADMIN},
    ReturnStatus.CLOSED: {Role.FINANCE, Role.ADMIN},
    ReturnStatus.REJECTED: {Role.CUSTOMER_SERVICE, Role.FINANCE, Role.ADMIN},
}

SYSTEM_TARGETS = {
    ReturnStatus.REFUND_PENDING,
    ReturnStatus.REFUND_UNKNOWN,
    ReturnStatus.NEEDS_RECONCILIATION,
    ReturnStatus.REFUNDED,
}


def assert_transition(current: ReturnStatus, target: ReturnStatus) -> None:
    if target not in TRANSITIONS[current]:
        raise InvalidTransition(f"cannot move return from {current.value} to {target.value}")


def assert_actor_can_transition(
    role: Role | None, target: ReturnStatus, *, system: bool = False
) -> None:
    if target in SYSTEM_TARGETS:
        if not system:
            raise PermissionDenied(f"{target.value} is a system-owned transition")
        return
    allowed = ROLE_BY_TARGET.get(target)
    if allowed is not None and role not in allowed:
        raise PermissionDenied(f"role {role!s} cannot transition a return to {target.value}")


def assert_approved_amount(requested_minor: int, approved_minor: int) -> None:
    if approved_minor <= 0:
        raise ValidationFailure("approved refund amount must be positive")
    if approved_minor > requested_minor:
        raise ValidationFailure("approved refund amount cannot exceed requested amount")
