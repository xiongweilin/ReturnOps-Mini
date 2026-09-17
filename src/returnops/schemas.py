from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator

from returnops.domain.states import ReturnStatus


class ReturnCreate(BaseModel):
    external_order_ref: str = Field(min_length=1, max_length=120)
    customer_ref: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=2000)
    requested_amount_minor: int = Field(gt=0, le=100_000_000)
    currency: str = Field(default="USD", min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()


class VersionedAction(BaseModel):
    expected_version: int = Field(ge=1)


class AuthorizeRequest(VersionedAction):
    rationale: str | None = Field(default=None, max_length=2000)


class InspectRequest(VersionedAction):
    notes: str = Field(min_length=1, max_length=4000)


class ApproveRefundRequest(VersionedAction):
    approved_amount_minor: int = Field(gt=0, le=100_000_000)
    rationale: str | None = Field(default=None, max_length=2000)


class RejectRequest(VersionedAction):
    reason: str = Field(min_length=1, max_length=2000)


class ReturnView(BaseModel):
    id: uuid.UUID
    organizationId: uuid.UUID
    caseRef: str
    externalOrderRef: str
    customerRef: str
    reason: str
    requestedAmountMinor: int
    approvedAmountMinor: int | None
    currency: str
    status: ReturnStatus
    version: int
    inspectionNotes: str | None
    rejectionReason: str | None
    createdAt: str
    updatedAt: str


class RefundApprovalResponse(BaseModel):
    case: dict[str, Any]
    secondApprovalRequired: bool


class IdempotentResponse(BaseModel):
    replayed: bool
    result: dict[str, Any]


class PaymentWebhook(BaseModel):
    event_id: str
    refund_id: str | None = None
    idempotency_key: str
    status: str
    amount_minor: int | None = None
    currency: str | None = None
