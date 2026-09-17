from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from returnops.db import get_session
from returnops.errors import AuthenticationError
from returnops.models import User
from returnops.services.tenancy import TenantContext, authenticate, resolve_tenant


def _bearer(authorization: str | None) -> str:
    if not authorization:
        raise AuthenticationError("missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthenticationError("Authorization must use Bearer <token>")
    return token


def current_user(
    db: Annotated[Session, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    return authenticate(db, _bearer(authorization))


def tenant_context(
    db: Annotated[Session, Depends(get_session)],
    user: Annotated[User, Depends(current_user)],
    organization_id: Annotated[uuid.UUID, Header(alias="X-Organization-ID")],
) -> TenantContext:
    return resolve_tenant(db, user=user, organization_id=organization_id)
