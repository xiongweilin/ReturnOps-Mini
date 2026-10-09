from __future__ import annotations

import hashlib
import secrets
import threading
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from returnops.config import get_settings
from returnops.domain.states import Role
from returnops.errors import AuthenticationError, NotFound, PermissionDenied
from returnops.models import Membership, Organization, User

DEMO_SESSION_COOKIE = "returnops_demo_session"
_HUMAN_DEMO_ROLES = {
    Role.CUSTOMER_SERVICE,
    Role.WAREHOUSE,
    Role.FINANCE,
    Role.ADMIN,
}


@dataclass(frozen=True)
class _DemoSession:
    user_id: uuid.UUID
    organization_id: uuid.UUID
    expires_at: float


_sessions: dict[str, _DemoSession] = {}
_sessions_lock = threading.Lock()


def demo_mode_enabled() -> bool:
    settings = get_settings()
    return settings.demo_mode and settings.environment == "demo"


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_demo_session(
    db: Session, *, role: Role, finance_slot: int = 0
) -> tuple[str, Organization, User, int]:
    if not demo_mode_enabled():
        raise PermissionDenied("demo identities are disabled outside the local demo environment")
    if role not in _HUMAN_DEMO_ROLES:
        raise PermissionDenied("role is not available in the demo sign-in")
    if role is not Role.FINANCE and finance_slot != 0:
        raise PermissionDenied("finance slot is only available for finance identities")

    settings = get_settings()
    organization = db.execute(
        select(Organization).where(Organization.name == settings.demo_organization_name)
    ).scalar_one_or_none()
    if organization is None:
        raise NotFound("demo organization is not initialized")

    users = list(
        db.execute(
            select(User)
            .join(Membership, Membership.user_id == User.id)
            .where(
                Membership.organization_id == organization.id,
                Membership.role == role,
                User.is_active.is_(True),
            )
            .order_by(User.email)
        )
        .scalars()
        .all()
    )
    if finance_slot >= len(users):
        raise NotFound("requested demo identity is not initialized")

    user = users[finance_slot]
    token = secrets.token_urlsafe(32)
    expires_at = time.monotonic() + settings.demo_session_ttl_seconds
    session = _DemoSession(user_id=user.id, organization_id=organization.id, expires_at=expires_at)
    with _sessions_lock:
        _sessions[_digest(token)] = session
    return token, organization, user, settings.demo_session_ttl_seconds


def resolve_demo_session(db: Session, token: str) -> tuple[User, uuid.UUID, Role]:
    if not demo_mode_enabled():
        raise AuthenticationError("demo sessions are disabled")

    key = _digest(token)
    now = time.monotonic()
    with _sessions_lock:
        session = _sessions.get(key)
        if session is None or session.expires_at <= now:
            _sessions.pop(key, None)
            raise AuthenticationError("invalid or expired demo session")

    user = db.get(User, session.user_id)
    membership = db.execute(
        select(Membership).where(
            Membership.user_id == session.user_id,
            Membership.organization_id == session.organization_id,
        )
    ).scalar_one_or_none()
    if user is None or not user.is_active or membership is None:
        with _sessions_lock:
            _sessions.pop(key, None)
        raise AuthenticationError("demo identity is no longer active")
    return user, session.organization_id, membership.role


def revoke_demo_session(token: str) -> None:
    with _sessions_lock:
        _sessions.pop(_digest(token), None)
