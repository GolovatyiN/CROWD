"""Donor matching service.

Picks the best donor for a given AnchorPlanItem, respecting:
- donor.is_active == True
- geo / language match (case-insensitive; empty fields on either side = wildcard)
- required_link_type compatibility (dofollow ↔ dofollow|mixed, nofollow ↔ nofollow|mixed,
  empty/unknown ↔ any)
- exclusion: pairs (target_url, donor_url) already present in StopListEntry or in
  successful Placements
- donors not already assigned to other items in the same plan for the same target_url
  (avoid duplicate proposals inside one plan)
- ranked by composite quality score (TR, organic traffic, ref domains, backlinks)

The implementation is intentionally pure-Python on top of SQLAlchemy queries so
the rules are easy to tweak in one place.
"""

from __future__ import annotations

import math
from typing import Iterable, Optional, Sequence
from urllib.parse import urlparse

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    AnchorPlanItem,
    Donor,
    DonorAccount,
    Placement,
    StopListEntry,
)


# ---------- helpers ----------

def extract_domain(url: str) -> str:
    if not url:
        return ""
    raw = url.strip()
    if "://" not in raw:
        raw = "http://" + raw
    try:
        host = urlparse(raw).netloc.lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def link_type_compatible(required: str, donor_type: str) -> bool:
    req = _norm(required)
    dt = _norm(donor_type)
    if not req or req == "unknown":
        return True
    if req == dt:
        return True
    if dt == "mixed":
        return True
    return False


def quality_score(donor: Donor) -> float:
    """Composite score; higher is better. log-dampened to avoid one huge metric eating the rest."""
    s = 0.0
    s += (donor.tr or 0) * settings.score_tr_weight
    s += math.log1p(max(donor.organic_traffic or 0, 0)) * settings.score_traffic_weight
    s += math.log1p(max(donor.ref_domains or 0, 0)) * settings.score_refdomains_weight
    s += math.log1p(max(donor.backlinks or 0, 0)) * settings.score_backlinks_weight
    return s


# ---------- core ----------

def _blocked_donor_urls_for_target(db: Session, target_url: str) -> set[str]:
    """donor_urls that the given target_url is forbidden to use."""
    if not target_url:
        return set()
    out: set[str] = set()
    # From stop list
    rows = db.execute(
        select(StopListEntry.donor_url).where(StopListEntry.target_url == target_url)
    ).all()
    out.update(r[0] for r in rows if r[0])
    # From successful placements (placed/done)
    rows = db.execute(
        select(Placement.donor_url).where(
            and_(
                Placement.target_url == target_url,
                Placement.status.in_(["placed", "done"]),
            )
        )
    ).all()
    out.update(r[0] for r in rows if r[0])
    return out


def _candidates_query(db: Session, item: AnchorPlanItem):
    q = select(Donor).where(Donor.is_active.is_(True))
    geo = _norm(item.geo)
    if geo:
        q = q.where(or_(Donor.geo == "", Donor.geo.ilike(geo)))
    lang = _norm(item.language)
    if lang:
        q = q.where(or_(Donor.language == "", Donor.language.ilike(lang)))
    return q


def find_best_donor(
    db: Session,
    item: AnchorPlanItem,
    *,
    exclude_donor_ids: Optional[Iterable[int]] = None,
) -> Optional[Donor]:
    blocked_urls = _blocked_donor_urls_for_target(db, item.target_url)
    excluded_ids = set(exclude_donor_ids or [])

    donors: Sequence[Donor] = db.execute(_candidates_query(db, item)).scalars().all()

    eligible: list[Donor] = []
    for d in donors:
        if d.id in excluded_ids:
            continue
        if d.donor_url in blocked_urls:
            continue
        if not link_type_compatible(item.required_link_type, d.link_type):
            continue
        eligible.append(d)

    if not eligible:
        return None
    eligible.sort(key=quality_score, reverse=True)
    return eligible[0]


def auto_match_plan(db: Session, plan_id: int) -> dict:
    """Walk all not-yet-matched items in a plan and assign a donor where possible.

    Returns counters and per-item status updates. Caller commits.
    """
    items = db.execute(
        select(AnchorPlanItem).where(
            and_(
                AnchorPlanItem.anchor_plan_id == plan_id,
                AnchorPlanItem.status.in_(["new", "problem"]),
                AnchorPlanItem.selected_donor_id.is_(None),
            )
        )
    ).scalars().all()

    matched = 0
    problem_items: list[int] = []
    # Avoid suggesting the same donor twice for the same target_url within this batch.
    used_per_target: dict[str, set[int]] = {}

    for item in items:
        used_ids = used_per_target.setdefault(item.target_url, set())
        donor = find_best_donor(db, item, exclude_donor_ids=used_ids)
        if donor is None:
            item.status = "problem"
            if not item.comment:
                item.comment = "Подходящий донор не найден (гео / язык / тип ссылки / стоп-лист)"
            problem_items.append(item.id)
            continue
        item.selected_donor_id = donor.id
        if item.status in ("new", "problem"):
            item.status = "donor_selected"
        used_ids.add(donor.id)
        matched += 1

    return {
        "matched": matched,
        "not_matched": len(problem_items),
        "items_problem": problem_items,
    }


def account_usage(db: Session, donor_id: int) -> dict[int, int]:
    """How many placements each account on this donor already has."""
    from sqlalchemy import func
    rows = db.execute(
        select(Placement.donor_account_id, func.count(Placement.id))
        .where(Placement.donor_id == donor_id)
        .group_by(Placement.donor_account_id)
    ).all()
    return {acc_id: cnt for acc_id, cnt in rows if acc_id is not None}


def suggest_account(db: Session, donor_id: int) -> Optional[DonorAccount]:
    """Pick the least-used active account on a donor that still has capacity.

    Strategy:
    - Only active accounts.
    - Drop accounts that have reached their `max_placements` cap (cap=0 means no limit).
    - Prefer the one with the fewest placements; ties broken by id ascending.
    """
    accounts: list[DonorAccount] = db.execute(
        select(DonorAccount).where(
            and_(DonorAccount.donor_id == donor_id, DonorAccount.is_active.is_(True))
        )
    ).scalars().all()
    if not accounts:
        return None

    usage = account_usage(db, donor_id)
    eligible = [a for a in accounts if not a.max_placements or usage.get(a.id, 0) < a.max_placements]
    if not eligible:
        return None
    eligible.sort(key=lambda a: (usage.get(a.id, 0), a.id))
    return eligible[0]
