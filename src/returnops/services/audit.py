from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from returnops.models import AuditEvent


def record_audit(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        before_json=before,
        after_json=after,
        metadata_json=metadata,
    )
    db.add(event)
    db.flush()
    return event
