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
import time
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


# In-process cache for the donor pool — auto_match_plan fetches every active
# donor on every run. With Neon's metered transfer that's expensive when the
# user clicks "Подобрать" several times in a row. 60-second TTL means
# back-to-back clicks reuse the same snapshot. Invalidated automatically by
# expiry; reads happen on every request anyway when donors get imported the
# cache becomes stale within a minute.
_DONOR_CACHE: dict = {"at": 0.0, "records": None}
_DONOR_CACHE_TTL = 60.0  # seconds


def _load_donor_pool(db: Session) -> list[dict]:
    now = time.time()
    if _DONOR_CACHE["records"] is not None and now - _DONOR_CACHE["at"] < _DONOR_CACHE_TTL:
        return _DONOR_CACHE["records"]
    rows = db.execute(
        select(
            Donor.id, Donor.donor_url, Donor.geo, Donor.language,
            Donor.link_type, Donor.tr, Donor.organic_traffic,
            Donor.ref_domains, Donor.backlinks,
        ).where(Donor.is_active.is_(True))
    ).all()
    records: list[dict] = []
    for d_id, d_url, d_geo, d_lang, d_lt, d_tr, d_traf, d_ref, d_back in rows:
        score = (
            (d_tr or 0) * settings.score_tr_weight
            + math.log1p(max(d_traf or 0, 0)) * settings.score_traffic_weight
            + math.log1p(max(d_ref or 0, 0)) * settings.score_refdomains_weight
            + math.log1p(max(d_back or 0, 0)) * settings.score_backlinks_weight
        )
        records.append({
            "id": d_id,
            "donor_url": d_url,
            # Keep both the raw value and the normalised code. A non-empty raw
            # geo that fails to normalise must NOT be treated as "worldwide" —
            # that bug let Bosnian/Macedonian donors match Austrian targets.
            "geo_raw": (d_geo or "").strip(),
            "geo_norm": normalize_country(d_geo or ""),
            "lang_raw": (d_lang or "").strip(),
            "lang_norm": normalize_language(d_lang or ""),
            "link_type": (d_lt or "").lower(),
            "score": score,
        })
    _DONOR_CACHE["records"] = records
    _DONOR_CACHE["at"] = now
    return records


def invalidate_donor_cache() -> None:
    """Called from import / create / update routes so the pool refreshes."""
    _DONOR_CACHE["records"] = None
    _DONOR_CACHE["at"] = 0.0


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

def _blocked_donor_urls_for_target(db: Session, target_url: str, anchor_text: str = "") -> set[str]:
    """donor_urls forbidden for THIS anchor (target_url + anchor_text).

    A donor is blocked only within the same anchor: if it was already used
    for (target_url, anchor_text) it can't be reused for that anchor, but it
    stays available for other anchors — even ones with the same target_url.
    """
    if not target_url:
        return set()
    out: set[str] = set()
    rows = db.execute(
        select(StopListEntry.donor_url).where(
            and_(
                StopListEntry.target_url == target_url,
                StopListEntry.anchor_text == (anchor_text or ""),
            )
        )
    ).all()
    out.update(r[0] for r in rows if r[0])
    rows = db.execute(
        select(Placement.donor_url).where(
            and_(
                Placement.target_url == target_url,
                Placement.anchor_text == (anchor_text or ""),
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
    - If the donor has a genuinely empty geo (worldwide), it's fine too.
    - Otherwise the donor's geo must normalise to the item's country.
      A non-empty geo we can't normalise is treated as a mismatch — we do
      NOT assume "unknown == worldwide" (that put Bosnian donors on Austrian
      targets).
    """
    if not item_geo_norm:
        return True
    if not (donor_geo or "").strip():
        return True
    return normalize_country(donor_geo) == item_geo_norm


def _lang_compatible(item_lang_norm: str, donor_lang: str) -> bool:
    if not item_lang_norm:
        return True
    if not (donor_lang or "").strip():
        return True
    return normalize_language(donor_lang) == item_lang_norm


def find_best_donor(
    db: Session,
    item: AnchorPlanItem,
    *,
    exclude_donor_ids: Optional[Iterable[int]] = None,
) -> Optional[Donor]:
    blocked_urls = _blocked_donor_urls_for_target(db, item.target_url, item.anchor_text or "")
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

    # ---- pre-compute donor pool (cached) ----
    donor_records = _load_donor_pool(db)

    # ---- bulk-load blocked donor_urls, keyed per ANCHOR (target_url, anchor_text) ----
    # A donor is blocked only within the same anchor, so the key includes the
    # anchor text — the same donor stays free for other anchors of the same
    # target_url.
    target_urls = {it.target_url for it in items if it.target_url}
    blocked_by_anchor: dict[tuple, set[str]] = {}
    if target_urls:
        for tu, at, du in db.execute(
            select(StopListEntry.target_url, StopListEntry.anchor_text, StopListEntry.donor_url)
            .where(StopListEntry.target_url.in_(target_urls))
        ).all():
            blocked_by_anchor.setdefault((tu, at or ""), set()).add(du)
        for tu, at, du in db.execute(
            select(Placement.target_url, Placement.anchor_text, Placement.donor_url)
            .where(
                Placement.target_url.in_(target_urls),
                Placement.status.in_(["placed", "done"]),
            )
        ).all():
            blocked_by_anchor.setdefault((tu, at or ""), set()).add(du)

    # ---- per-item pick ----
    matched = 0
    problem_items: list[int] = []
    # Within this run, don't suggest the same donor twice for the SAME anchor.
    # Different anchors (even same target_url) keep independent used-sets.
    used_per_anchor: dict[tuple, set[int]] = {}

    for item in items:
        anchor_key = (item.target_url, item.anchor_text or "")
        used_ids = used_per_anchor.setdefault(anchor_key, set())
        blocked_urls = blocked_by_anchor.get(anchor_key, set())
        item_geo = normalize_country(item.geo or "")
        item_lang = normalize_language(item.language or "")
        req_lt = (item.required_link_type or "").lower()
        require_lt = req_lt and req_lt != "unknown"

        best = None
        best_score = -1.0
        # Track how many donors were dropped by each filter so we can tell
        # the user which dimension actually blocked the match.
        dropped_link = dropped_geo = dropped_lang = 0
        passed_filters = 0
        for d in donor_records:
            if d["id"] in used_ids:
                continue
            if d["donor_url"] in blocked_urls:
                continue
            if require_lt and d["link_type"] != req_lt and d["link_type"] != "mixed":
                dropped_link += 1
                continue
            # GEO: a donor matches only if it's worldwide (no geo at all) OR
            # its geo resolves to the item's country. A donor that DOES carry
            # a geo we couldn't normalise is NOT a wildcard — exclude it.
            if item_geo and d["geo_raw"] and d["geo_norm"] != item_geo:
                dropped_geo += 1
                continue
            if item_lang and d["lang_raw"] and d["lang_norm"] != item_lang:
                dropped_lang += 1
                continue
            passed_filters += 1
            if d["score"] > best_score:
                best = d
                best_score = d["score"]

        if best is None:
            item.status = "problem"
            item.comment = _explain_no_match(
                item_geo, item_lang, req_lt,
                dropped_link, dropped_geo, dropped_lang,
                used_ids_count=len(used_ids),
                pool_size=len(donor_records),
            )
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


def _explain_no_match(
    item_geo: str, item_lang: str, req_lt: str,
    dropped_link: int, dropped_geo: int, dropped_lang: int,
    *, used_ids_count: int, pool_size: int,
) -> str:
    """Compose a human-friendly comment explaining what blocked the match.

    The biggest "dropped_X" tells us which filter ate the candidates. If a
    filter dropped *everything*, we name the constraint directly.
    """
    if pool_size == 0:
        return "В базе нет активных доноров"
    parts = []
    if item_geo and dropped_geo and dropped_geo >= max(dropped_link, dropped_lang):
        parts.append(f"в базе нет активных доноров с GEO={item_geo}")
    elif item_lang and dropped_lang and dropped_lang >= max(dropped_link, dropped_geo):
        parts.append(f"в базе нет активных доноров с языком={item_lang}")
    elif req_lt and dropped_link and dropped_link >= max(dropped_geo, dropped_lang):
        parts.append(f"в базе нет доноров с типом ссылки={req_lt}")
    if not parts:
        # Pool exists but everything got filtered by combined constraints, or
        # all remaining donors are already used for this target.
        if used_ids_count:
            parts.append(f"все подходящие доноры ({used_ids_count}) уже привязаны к этой цели")
        else:
            parts.append("подходящих доноров не найдено по совокупности фильтров")
    return "Подбор: " + "; ".join(parts)


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
