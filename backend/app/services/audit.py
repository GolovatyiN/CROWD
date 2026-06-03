"""Helpers for appending entries to the audit_logs table.

Use these from any admin-side route that mutates accounts so we have a record
of who did what. The functions never commit themselves — let the calling
route own the transaction boundary.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import AuditLog, User


def log(
    db: Session,
    actor: Optional[User],
    action: str,
    *,
    target: Optional[User] = None,
    target_id: Optional[int] = None,
    target_label: str = "",
    target_type: Optional[str] = None,
    **details: Any,
) -> AuditLog:
    """Record a single audit event.

    Args:
        actor: Who performed the action. None for system / unauthenticated
            (rare — usually a current_user dependency).
        action: Dot-separated event name, e.g. 'user.create', 'donor.bulk_delete'.
        target: The user being acted on (when applicable).
        target_id: Numeric id if target object isn't a User row.
        target_label: Human-readable label (email, name, domain…).
        target_type: Entity category ('user', 'donor', 'plan', 'system', …).
            Defaults to the action's prefix ('donor.bulk_delete' → 'donor'),
            keeping older user.* events tagged 'user' exactly as before.
        **details: Extra context — stored as JSON in the `details` column.

    Returns the freshly added AuditLog row.
    """
    if target is not None:
        target_id = target.id
        target_label = target_label or (target.email or "")
    if target_type is None:
        if target is not None or "user" in action:
            target_type = "user"
        else:
            target_type = action.split(".", 1)[0] if "." in action else ""
    entry = AuditLog(
        actor_id=actor.id if actor else None,
        actor_email=(actor.email if actor else ""),
        action=action,
        target_type=target_type[:32],
        target_id=target_id,
        target_label=target_label[:255],
        details=json.dumps(details, ensure_ascii=False, default=str)[:4000],
    )
    db.add(entry)
    return entry
