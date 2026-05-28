"""CSV/XLSX import helpers.

Strategy:
- Read into a pandas DataFrame.
- Normalize column names: lowercase, strip, collapse spaces -> underscore.
- Apply per-entity synonyms (e.g., dr -> tr, traffic -> organic_traffic).
- Map rows to dicts, validate, dedupe.
"""

from __future__ import annotations

import io
import json
import re
from typing import Iterable, Optional

import pandas as pd
from sqlalchemy.orm import Session

from ..models import (
    AnchorPlan,
    AnchorPlanItem,
    Donor,
    ImportLog,
    StopListEntry,
)
from .matcher import extract_domain


# ---------- shared ----------

def _normalize_col(name: str) -> str:
    s = str(name or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def _read_table(file_bytes: bytes, filename: str) -> pd.DataFrame:
    name = (filename or "").lower()
    bio = io.BytesIO(file_bytes)
    if name.endswith(".xlsx") or name.endswith(".xls"):
        df = pd.read_excel(bio, dtype=object)
    else:
        # try utf-8 first then fallback
        try:
            df = pd.read_csv(bio, dtype=object)
        except UnicodeDecodeError:
            bio.seek(0)
            df = pd.read_csv(bio, dtype=object, encoding="cp1251")
    df.columns = [_normalize_col(c) for c in df.columns]
    df = df.where(pd.notnull(df), None)
    return df


def _apply_synonyms(df: pd.DataFrame, synonyms: dict[str, str]) -> pd.DataFrame:
    rename = {col: synonyms[col] for col in df.columns if col in synonyms}
    if rename:
        df = df.rename(columns=rename)
    return df


def _to_int(v) -> int:
    if v is None or v == "":
        return 0
    try:
        return int(float(str(v).replace(",", ".").replace(" ", "")))
    except Exception:
        return 0


def _to_float(v) -> float:
    if v is None or v == "":
        return 0.0
    try:
        return float(str(v).replace(",", ".").replace(" ", ""))
    except Exception:
        return 0.0


def _to_str(v) -> str:
    if v is None:
        return ""
    return str(v).strip()


# ---------- Donors ----------

DONOR_SYNONYMS = {
    "url": "donor_url",
    "donor": "donor_url",
    "site": "donor_url",
    "website": "donor_url",
    "domain": "donor_url",  # users often have only the domain (e.g. "nunn.asia")
    "host": "donor_url",
    "dr": "tr",
    "trust_rank": "tr",
    "trust": "tr",
    "traffic": "organic_traffic",
    "organic": "organic_traffic",
    "organic_traffic": "organic_traffic",
    "refdomains": "ref_domains",
    "referring_domains": "ref_domains",
    "ref": "ref_domains",
    "ref_domains": "ref_domains",
    "backlinks": "backlinks",
    "backlinks_count": "backlinks",
    "country": "geo",
    "geo": "geo",
    "lang": "language",
    "language": "language",
    "type": "link_type",
    "linktype": "link_type",
    "link_type": "link_type",
    "niche": "category",
    "topic": "category",
    "category": "category",
    "notes": "comment",
    "comment": "comment",
}


def import_donors(db: Session, file_bytes: bytes, filename: str, user_id: Optional[int]) -> dict:
    df = _apply_synonyms(_read_table(file_bytes, filename), DONOR_SYNONYMS)
    errors: list[dict] = []
    inserted = updated = skipped = failed = 0

    if "donor_url" not in df.columns:
        raise ValueError("В файле нет обязательной колонки 'donor_url' (или url/site/website)")

    seen_in_file: set[str] = set()
    for idx, row in df.iterrows():
        url = _to_str(row.get("donor_url"))
        if not url:
            failed += 1
            errors.append({"row": int(idx) + 2, "error": "пустой donor_url"})
            continue
        if url in seen_in_file:
            skipped += 1
            continue
        seen_in_file.add(url)

        existing = db.query(Donor).filter(Donor.donor_url == url).one_or_none()
        payload = dict(
            donor_url=url,
            domain=extract_domain(url),
            tr=_to_float(row.get("tr")),
            organic_traffic=_to_int(row.get("organic_traffic")),
            ref_domains=_to_int(row.get("ref_domains")),
            backlinks=_to_int(row.get("backlinks")),
            geo=_to_str(row.get("geo")),
            language=_to_str(row.get("language")),
            link_type=(_to_str(row.get("link_type")) or "unknown").lower(),
            category=_to_str(row.get("category")),
            comment=_to_str(row.get("comment")),
        )
        try:
            if existing:
                for k, v in payload.items():
                    setattr(existing, k, v)
                updated += 1
            else:
                d = Donor(added_by=user_id, **payload)
                db.add(d)
                inserted += 1
        except Exception as e:
            failed += 1
            errors.append({"row": int(idx) + 2, "error": str(e)[:200]})

    log = ImportLog(
        type="donors",
        file_name=filename,
        rows_total=int(len(df)),
        rows_inserted=inserted,
        rows_updated=updated,
        rows_skipped=skipped,
        rows_failed=failed,
        errors_json=json.dumps(errors[:200], ensure_ascii=False),
        created_by=user_id,
    )
    db.add(log)
    db.flush()
    return {
        "rows_total": int(len(df)),
        "rows_inserted": inserted,
        "rows_updated": updated,
        "rows_skipped": skipped,
        "rows_failed": failed,
        "errors": errors[:50],
        "log_id": log.id,
    }


# ---------- Anchor plans ----------

PLAN_SYNONYMS = {
    "url": "target_url",
    "page": "target_url",
    "anchor": "anchor_text",
    "anchortext": "anchor_text",
    "domain": "target_domain",
    "target": "target_url",
    "country": "geo",
    "lang": "language",
    "type": "required_link_type",
    "link_type": "required_link_type",
    "linktype": "required_link_type",
    "requirement": "requirements",
    "notes": "requirements",
}


def import_anchor_plan(
    db: Session,
    file_bytes: bytes,
    filename: str,
    plan_name: str,
    user_id: Optional[int],
) -> dict:
    df = _apply_synonyms(_read_table(file_bytes, filename), PLAN_SYNONYMS)
    if "target_url" not in df.columns and "target_domain" not in df.columns:
        raise ValueError("В файле нет обязательной колонки 'target_url' (или domain/url/target)")

    plan = AnchorPlan(
        plan_name=plan_name or filename or "Анкор-план",
        uploaded_file_name=filename,
        created_by=user_id,
    )
    db.add(plan)
    db.flush()

    errors: list[dict] = []
    inserted = failed = 0
    for idx, row in df.iterrows():
        target_url = _to_str(row.get("target_url"))
        target_domain = _to_str(row.get("target_domain")) or extract_domain(target_url)
        if not target_url and not target_domain:
            failed += 1
            errors.append({"row": int(idx) + 2, "error": "пустые target_url и target_domain"})
            continue
        try:
            item = AnchorPlanItem(
                anchor_plan_id=plan.id,
                target_url=target_url,
                target_domain=target_domain,
                anchor_text=_to_str(row.get("anchor_text")),
                geo=_to_str(row.get("geo")),
                language=_to_str(row.get("language")),
                required_link_type=(_to_str(row.get("required_link_type")) or "").lower(),
                requirements=_to_str(row.get("requirements")),
                status="new",
            )
            db.add(item)
            inserted += 1
        except Exception as e:
            failed += 1
            errors.append({"row": int(idx) + 2, "error": str(e)[:200]})

    log = ImportLog(
        type="anchor_plan",
        file_name=filename,
        rows_total=int(len(df)),
        rows_inserted=inserted,
        rows_updated=0,
        rows_skipped=0,
        rows_failed=failed,
        errors_json=json.dumps(errors[:200], ensure_ascii=False),
        created_by=user_id,
    )
    db.add(log)
    db.flush()
    return {
        "rows_total": int(len(df)),
        "rows_inserted": inserted,
        "rows_updated": 0,
        "rows_skipped": 0,
        "rows_failed": failed,
        "errors": errors[:50],
        "log_id": log.id,
        "plan_id": plan.id,
    }


# ---------- Stop list ----------

STOPLIST_SYNONYMS = {
    "url": "target_url",
    "page": "target_url",
    "domain": "target_domain",
    "target": "target_url",
    "donor": "donor_url",
    "donor_site": "donor_url",
    "donor_link": "donor_url",
    "placed": "placed_at",
    "date": "placed_at",
    "result": "result_url",
    "result_link": "result_url",
    "notes": "comment",
}


def import_stop_list(db: Session, file_bytes: bytes, filename: str, user_id: Optional[int]) -> dict:
    df = _apply_synonyms(_read_table(file_bytes, filename), STOPLIST_SYNONYMS)
    if "donor_url" not in df.columns:
        raise ValueError("В файле нет обязательной колонки 'donor_url'")
    if "target_url" not in df.columns and "target_domain" not in df.columns:
        raise ValueError("В файле нет колонок 'target_url' или 'target_domain'")

    errors: list[dict] = []
    inserted = skipped = failed = 0
    for idx, row in df.iterrows():
        donor_url = _to_str(row.get("donor_url"))
        target_url = _to_str(row.get("target_url"))
        target_domain = _to_str(row.get("target_domain")) or extract_domain(target_url)
        if not donor_url or (not target_url and not target_domain):
            failed += 1
            errors.append({"row": int(idx) + 2, "error": "пустые donor_url или target_url"})
            continue
        if not target_url:
            target_url = target_domain  # fall back so the UNIQUE constraint still works

        exists = db.query(StopListEntry).filter(
            StopListEntry.target_url == target_url,
            StopListEntry.donor_url == donor_url,
        ).first()
        if exists:
            skipped += 1
            continue

        donor = db.query(Donor).filter(Donor.donor_url == donor_url).first()
        entry = StopListEntry(
            target_url=target_url,
            target_domain=target_domain or extract_domain(target_url),
            donor_url=donor_url,
            donor_id=donor.id if donor else None,
            result_url=_to_str(row.get("result_url")),
            comment=_to_str(row.get("comment")),
            placed_by=user_id,
            source_anchor_plan="(импортировано)",
        )
        db.add(entry)
        inserted += 1

    log = ImportLog(
        type="stop_list",
        file_name=filename,
        rows_total=int(len(df)),
        rows_inserted=inserted,
        rows_updated=0,
        rows_skipped=skipped,
        rows_failed=failed,
        errors_json=json.dumps(errors[:200], ensure_ascii=False),
        created_by=user_id,
    )
    db.add(log)
    db.flush()
    return {
        "rows_total": int(len(df)),
        "rows_inserted": inserted,
        "rows_updated": 0,
        "rows_skipped": skipped,
        "rows_failed": failed,
        "errors": errors[:50],
        "log_id": log.id,
    }


# ---------- Export helpers ----------

def donors_to_csv(donors: Iterable[Donor]) -> str:
    df = pd.DataFrame([{
        "Domain": d.domain or d.donor_url,
        "DR": d.tr,
        "Organic Traffic": d.organic_traffic,
        "Referring Domains": d.ref_domains,
        "Backlinks": d.backlinks,
        "GEO": d.geo,
        "Language": d.language,
        "link_type": d.link_type,
        "Category": d.category,
        "Status": d.status,
        "Comment": d.comment,
        "Active": d.is_active,
    } for d in donors])
    return df.to_csv(index=False)


def stop_list_to_csv(rows: Iterable[StopListEntry]) -> str:
    df = pd.DataFrame([{
        "target_domain": r.target_domain,
        "target_url": r.target_url,
        "donor_url": r.donor_url,
        "anchor_text": r.anchor_text,
        "result_url": r.result_url,
        "account_username": r.account_username,
        "login_email": r.login_email,
        "placed_at": r.placed_at.isoformat() if r.placed_at else "",
        "source_anchor_plan": r.source_anchor_plan,
        "comment": r.comment,
    } for r in rows])
    return df.to_csv(index=False)


def plan_items_to_csv(items: Iterable[AnchorPlanItem]) -> str:
    df = pd.DataFrame([{
        "target_domain": it.target_domain,
        "target_url": it.target_url,
        "anchor_text": it.anchor_text,
        "geo": it.geo,
        "language": it.language,
        "required_link_type": it.required_link_type,
        "requirements": it.requirements,
        "selected_donor_id": it.selected_donor_id,
        "assigned_to": it.assigned_to,
        "status": it.status,
        "result_url": it.result_url,
        "comment": it.comment,
    } for it in items])
    return df.to_csv(index=False)
