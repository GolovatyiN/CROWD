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
from .geo import normalize_country, normalize_language


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
    """Active donors only — geo/language are checked in Python after the
    fetch because we need normalised comparison (Spain == ES == España)
    that's awkward to express in SQL.
    """
    return select(Donor).where(Donor.is_active.is_(True))


def _geo_compatible(item_geo_norm: str, donor_geo: str) -> bool:
    """True if the donor's geo can serve the item.

    - If the item has no geo, anything is fine.
    - If the donor has no geo (worldwide), it's fine too.
    - Otherwise both must normalise to the same ISO-2 country code.
    """
    if not item_geo_norm:
        return True
    if not donor_geo:
        return True
    return normalize_country(donor_geo) == item_geo_norm


def _lang_compatible(item_lang_norm: str, donor_lang: str) -> bool:
    if not item_lang_norm:
        return True
    if not donor_lang:
        return True
    return normalize_language(donor_lang) == item_lang_norm


def find_best_donor(
    db: Session,
    item: AnchorPlanItem,
    *,
    exclude_donor_ids: Optional[Iterable[int]] = None,
) -> Optional[Donor]:
    blocked_urls = _blocked_donor_urls_for_target(db, item.target_url)
    excluded_ids = set(exclude_donor_ids or [])
    item_geo = normalize_country(item.geo or "")
    item_lang = normalize_language(item.language or "")

    donors: Sequence[Donor] = db.execute(_candidates_query(db, item)).scalars().all()

    eligible: list[Donor] = []
    for d in donors:
        if d.id in excluded_ids:
            continue
        if d.donor_url in blocked_urls:
            continue
        if not link_type_compatible(item.required_link_type, d.link_type):
            continue
        if not _geo_compatible(item_geo, d.geo or ""):
            continue
        if not _lang_compatible(item_lang, d.language or ""):
            continue
        eligible.append(d)

    if not eligible:
        return None
    eligible.sort(key=quality_score, reverse=True)
    return eligible[0]


def auto_match_plan(db: Session, plan_id: int) -> dict:
    """Walk all items in a plan that still need a donor and pick the best one.

    Eligible = any item in this plan whose `selected_donor_id` is NULL and that
    isn't already considered finished (placed / done / rejected). Status
    doesn't matter otherwise — an item assigned to an employee still needs a
    donor, and the employee can't act until one is picked.

    Hot path: when a customer dumps 2000 rows and clicks "match", the naive
    implementation fires ~6000 SELECTs (find_best_donor + stop-list query +
    placements query × N items). With Postgres on a different continent that
    was *minutes*. This version pulls everything in **3 queries** and does
    all filtering / scoring in Python with pre-normalised values:

      1. fetch the eligible items
      2. fetch every active donor and pre-compute geo/lang/score
      3. fetch all blocked (target_url, donor_url) pairs in one IN()

    Then it's a single in-memory loop. 2000 items × 2000 donors ≈ 4M dirt
    cheap comparisons — well under a second.
    """
    items = db.execute(
        select(AnchorPlanItem).where(
            and_(
                AnchorPlanItem.anchor_plan_id == plan_id,
                AnchorPlanItem.selected_donor_id.is_(None),
                ~AnchorPlanItem.status.in_(["placed", "done", "rejected"]),
            )
        )
    ).scalars().all()
    if not items:
        return {"matched": 0, "not_matched": 0, "items_problem": [], "considered": 0}

    # ---- pre-compute donor pool ----
    donors_q = db.execute(select(Donor).where(Donor.is_active.is_(True))).scalars().all()
    donor_records: list[dict] = []
    for d in donors_q:
        donor_records.append({
            "id": d.id,
            "donor_url": d.donor_url,
            "geo_norm": normalize_country(d.geo or ""),
            "lang_norm": normalize_language(d.language or ""),
            "link_type": (d.link_type or "").lower(),
            "score": quality_score(d),
        })

    # ---- bulk-load blocked (target_url, donor_url) pairs ----
    target_urls = {it.target_url for it in items if it.target_url}
    blocked_by_target: dict[str, set[str]] = {}
    if target_urls:
        for tu, du in db.execute(
            select(StopListEntry.target_url, StopListEntry.donor_url)
            .where(StopListEntry.target_url.in_(target_urls))
        ).all():
            blocked_by_target.setdefault(tu, set()).add(du)
        for tu, du in db.execute(
            select(Placement.target_url, Placement.donor_url)
            .where(
                Placement.target_url.in_(target_urls),
                Placement.status.in_(["placed", "done"]),
            )
        ).all():
            blocked_by_target.setdefault(tu, set()).add(du)

    # ---- per-item pick ----
    matched = 0
    problem_items: list[int] = []
    used_per_target: dict[str, set[int]] = {}

    for item in items:
        used_ids = used_per_target.setdefault(item.target_url, set())
        blocked_urls = blocked_by_target.get(item.target_url, set())
        item_geo = normalize_country(item.geo or "")
        item_lang = normalize_language(item.language or "")
        req_lt = (item.required_link_type or "").lower()
        require_lt = req_lt and req_lt != "unknown"

        best = None
        best_score = -1.0
        for d in donor_records:
            if d["id"] in used_ids:
                continue
            if d["donor_url"] in blocked_urls:
                continue
            if require_lt and d["link_type"] != req_lt and d["link_type"] != "mixed":
                continue
            if item_geo and d["geo_norm"] and d["geo_norm"] != item_geo:
                continue
            if item_lang and d["lang_norm"] and d["lang_norm"] != item_lang:
                continue
            if d["score"] > best_score:
                best = d
                best_score = d["score"]

        if best is None:
            item.status = "problem"
            if not item.comment:
                item.comment = "Подходящий донор не найден (гео / язык / тип ссылки / стоп-лист)"
            problem_items.append(item.id)
            continue

        item.selected_donor_id = best["id"]
        if item.status in ("new", "problem"):
            item.status = "donor_selected"
        used_ids.add(best["id"])
        matched += 1

    return {
        "matched": matched,
        "not_matched": len(problem_items),
        "items_problem": problem_items,
        "considered": len(items),
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
