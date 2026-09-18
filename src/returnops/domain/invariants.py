from __future__ import annotations

from dataclasses import dataclass

from returnops.domain.states import ReturnStatus
from returnops.errors import Conflict


@dataclass(frozen=True)
class Invariant:
    key: str
    text: str


INVARIANTS = (
    Invariant("tenant_ownership", "Every business row belongs to exactly one organization."),
    Invariant("tenant_isolation", "A user may never read or mutate another organization’s return."),
    Invariant("state_machine", "Return status changes only through the declared state machine."),
    Invariant("cas", "Concurrent state writes use compare-and-swap on the return version."),
    Invariant("refund_gate", "No refund may be dispatched before explicit finance approval."),
    Invariant(
        "refund_ceiling", "Approved and executed refund amounts never exceed requested amount."
    ),
    Invariant("single_effect", "One return case has at most one active provider refund intent."),
    Invariant("unknown_no_retry", "Unknown provider outcomes are never blindly retried."),
    Invariant("webhook_dedup", "One provider webhook event changes business state at most once."),
    Invariant("evidence", "REFUNDED requires provider evidence, not a human status edit."),
    Invariant("four_eyes", "High-value refunds require two distinct finance approvers."),
    Invariant("closed_terminal", "CLOSED and REJECTED are terminal business states."),
)


def assert_refundable_status(status: ReturnStatus) -> None:
    if status is not ReturnStatus.REFUND_APPROVED:
        raise Conflict(f"refund dispatch requires refund_approved status, got {status.value}")
