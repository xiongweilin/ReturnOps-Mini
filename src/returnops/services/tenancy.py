from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from returnops.domain.states import Role
from returnops.errors import AuthenticationError, PermissionDenied
from returnops.models import Membership, User
from returnops.security import hash_token


@dataclass(frozen=True)
class TenantContext:
    organization_id: uuid.UUID
    user_id: uuid.UUID
    role: Role


def authenticate(db: Session, bearer_token: str) -> User:
    digest = hash_token(bearer_token)
    user = db.execute(select(User).where(User.api_token_hash == digest)).scalar_one_or_none()
    if user is None or not user.is_active:
        raise AuthenticationError("invalid or inactive API token")
    return user


def resolve_tenant(db: Session, *, user: User, organization_id: uuid.UUID) -> TenantContext:
    membership = db.execute(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.organization_id == organization_id,
        )
    ).scalar_one_or_none()
    if membership is None:
        raise PermissionDenied("user is not a member of this organization")
    return TenantContext(
        organization_id=organization_id,
        user_id=user.id,
        role=membership.role,
    )


def require_role(context: TenantContext, *roles: Role) -> None:
    if context.role is Role.ADMIN:
        return
    if context.role not in set(roles):
        names = ", ".join(role.value for role in roles)
        raise PermissionDenied(f"requires one of roles: {names}")
