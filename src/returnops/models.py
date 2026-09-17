from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from returnops.domain.states import (
    ApprovalDecision,
    ApprovalKind,
    RefundAttemptStatus,
    ReturnStatus,
    Role,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def uuid4() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    pass


class Organization(Base):
    __tablename__ = "organization"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class User(Base):
    __tablename__ = "user_account"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    api_token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Membership(Base):
    __tablename__ = "membership"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_membership_org_user"),
        Index("ix_membership_user_org", "user_id", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organization.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_account.id"), nullable=False)
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    organization: Mapped[Organization] = relationship()
    user: Mapped[User] = relationship()


class ReturnCase(Base):
    __tablename__ = "return_case"
    __table_args__ = (
        UniqueConstraint("organization_id", "case_ref", name="uq_return_case_org_ref"),
        Index("ix_return_case_org_status", "organization_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organization.id"), nullable=False)
    case_ref: Mapped[str] = mapped_column(String(80), nullable=False)
    external_order_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    customer_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    approved_amount_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    status: Mapped[ReturnStatus] = mapped_column(
        Enum(ReturnStatus, native_enum=False), default=ReturnStatus.REQUESTED, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_account.id"), nullable=False)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    inspection_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class Approval(Base):
    __tablename__ = "approval"
    __table_args__ = (
        UniqueConstraint("return_case_id", "kind", "user_id", name="uq_approval_case_kind_user"),
        Index("ix_approval_org_case", "organization_id", "return_case_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organization.id"), nullable=False)
    return_case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("return_case.id"), nullable=False)
    kind: Mapped[ApprovalKind] = mapped_column(Enum(ApprovalKind, native_enum=False), nullable=False)
    decision: Mapped[ApprovalDecision] = mapped_column(
        Enum(ApprovalDecision, native_enum=False), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_account.id"), nullable=False)
    amount_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class RefundAttempt(Base):
    __tablename__ = "refund_attempt"
    __table_args__ = (
        UniqueConstraint("return_case_id", name="uq_refund_attempt_case"),
        UniqueConstraint("provider_idempotency_key", name="uq_refund_provider_idempotency"),
        Index("ix_refund_attempt_org_status", "organization_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organization.id"), nullable=False)
    return_case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("return_case.id"), nullable=False)
    provider_idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[RefundAttemptStatus] = mapped_column(
        Enum(RefundAttemptStatus, native_enum=False), default=RefundAttemptStatus.PLANNED, nullable=False
    )
    provider_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    dispatch_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class WebhookReceipt(Base):
    __tablename__ = "webhook_receipt"
    __table_args__ = (UniqueConstraint("provider", "event_id", name="uq_webhook_provider_event"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    event_id: Mapped[str] = mapped_column(String(200), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_event"
    __table_args__ = (Index("ix_audit_org_resource", "organization_id", "resource_type", "resource_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organization.id"), nullable=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user_account.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(120), nullable=False)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_record"
    __table_args__ = (
        UniqueConstraint("organization_id", "scope", "key", name="uq_idempotency_org_scope_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organization.id"), nullable=False)
    scope: Mapped[str] = mapped_column(String(120), nullable=False)
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class OutboxEvent(Base):
    __tablename__ = "outbox_event"
    __table_args__ = (Index("ix_outbox_status_available", "status", "available_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organization.id"), nullable=True
    )
    topic: Mapped[str] = mapped_column(String(120), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(120), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
