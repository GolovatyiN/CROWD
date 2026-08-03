"""In-app notifications.

Created when a link check yields a problem status (link gone / wrong url / anchor
changed / page down / manual review). Recipients: the responsible manager (client
project or client manager) or, failing that, all active managers/admins. Deduped
by (user, dedup_key) within a window so a persistently-broken link isn't re-alerted
on every daily re-check.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from ..models import Client, ClientProject, Notification, Placement, User, utcnow
from .url_match import domain_of

# status → (human title, severity)
ALERT_STATUSES: dict[str, tuple[str, str]] = {
    "not_found": ("Ссылка пропала", "error"),
    "wrong_url": ("Ссылка ведёт не на тот URL", "error"),
    "wrong_anchor": ("Анкор не совпадает", "warning"),
    "anchor_changed": ("Анкор изменён", "warning"),
    "page_unavailable": ("Страница недоступна", "error"),
    "manual_required": ("Нужна ручная проверка", "warning"),
}

_DEDUP_WINDOW = timedelta(hours=72)


def create(db: Session, user_id: int, *, type: str, severity: str = "info",
           entity_type: str = "", entity_id: int | None = None, title: str = "",
           body: str = "", dedup_key: str = "") -> Notification | None:
    """Create a notification unless an equivalent one was created recently."""
    if dedup_key:
        cutoff = utcnow() - _DEDUP_WINDOW
        exists = (
            db.query(Notification.id)
            .filter(Notification.user_id == user_id, Notification.dedup_key == dedup_key,
                    Notification.created_at >= cutoff)
            .first()
        )
        if exists:
            return None
    n = Notification(
        user_id=user_id, type=type, severity=severity, entity_type=entity_type,
        entity_id=entity_id, title=title[:255], body=body, dedup_key=dedup_key[:255],
    )
    db.add(n)
    db.flush()
    return n


def _recipients(db: Session, placement: Placement) -> set[int]:
    ids: set[int] = set()
    if placement.client_project_id:
        proj = db.get(ClientProject, placement.client_project_id)
        if proj:
            if proj.manager_id:
                ids.add(proj.manager_id)
            client = db.get(Client, proj.client_id) if proj.client_id else None
            if client and client.manager_id:
                ids.add(client.manager_id)
    if not ids:
        for (uid,) in (
            db.query(User.id)
            .filter(User.is_active.is_(True), User.role.in_(["manager", "admin", "super_admin"]))
            .all()
        ):
            ids.add(uid)
    return ids


def maybe_alert(db: Session, placement: Placement, status: str) -> int:
    """If `status` is a problem, notify the responsible managers (deduped).
    Returns how many notifications were created."""
    meta = ALERT_STATUSES.get(status)
    if not meta:
        return 0
    label, severity = meta
    dedup = f"link:{placement.id}:{status}"
    title = f"{label}: {placement.target_url}"
    body = (f"Донор: {domain_of(placement.donor_url) or placement.donor_url}. "
            f"Размещение #{placement.id}. Ready link: {placement.result_url}")
    created = 0
    for uid in _recipients(db, placement):
        if create(db, uid, type=f"link.{status}", severity=severity, entity_type="placement",
                  entity_id=placement.id, title=title, body=body, dedup_key=dedup):
            created += 1
    return created
