"""Small shared helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def iso_utc(value: Optional[datetime]) -> Optional[str]:
    """Serialise a timestamp as an explicit-UTC ISO string (…+00:00).

    All timestamps in this app are stored as naive UTC (datetime.utcnow). Without
    a timezone marker, clients parse the string as *local* time and render it
    hours off. Stamping UTC makes it unambiguous so the frontend can convert to
    the viewer's local timezone.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()
