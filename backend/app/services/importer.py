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
from sqlalchemy.exc import IntegrityError, DataError
from sqlalchemy.orm import Session

from ..models import (
    AnchorPlan,
    AnchorPlanItem,
    Donor,
    ImportLog,
    StopListEntry,
)
from .matcher import extract_domain
from .geo import country_from_url, language_from_url, normalize_country, normalize_language


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
    # English
    "url": "donor_url",
    "donor": "donor_url",
    "donor_url": "donor_url",
    "site": "donor_url",
    "website": "donor_url",
    "domain": "donor_url",
    "host": "donor_url",
    "tr": "tr",
    "dr": "tr",
    "trust_rank": "tr",
    "trust": "tr",
    "rating": "tr",
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
    # Russian
    "донор": "donor_url",
    "сайт": "donor_url",
    "url_донора": "donor_url",
    "адрес": "donor_url",
    "домен_донора": "donor_url",
    "трафик": "organic_traffic",
    "органический_трафик": "organic_traffic",
    "посещаемость": "organic_traffic",
    "ссылающиеся_домены": "ref_domains",
    "реф_домены": "ref_domains",
    "ref_домены": "ref_domains",
    "бэклинки": "backlinks",
    "обратные_ссылки": "backlinks",
    "ссылки": "backlinks",
    "гео": "geo",
    "страна": "geo",
    "регион": "geo",
    "язык": "language",
    "тип": "link_type",
    "тип_ссылки": "link_type",
    "тематика": "category",
    "категория": "category",
    "комментарий": "comment",
    "примечание": "comment",
}


def import_donors(db: Session, file_bytes: bytes, filename: str, user_id: Optional[int]) -> dict:
    df = _apply_synonyms(_read_table(file_bytes, filename), DONOR_SYNONYMS)
    errors: list[dict] = []
    inserted = updated = skipped = failed = 0

    if "donor_url" not in df.columns:
        raise ValueError("В файле нет обязательной колонки 'donor_url' (или url/site/website/domain)")

    seen_in_file: set[str] = set()
    pending = 0
    BATCH = 200  # flush every N rows so a single bad row can't poison thousands

    for idx, row in df.iterrows():
        url = _to_str(row.get("donor_url"))
        if not url:
            failed += 1
            errors.append({"row": int(idx) + 2, "error": "пустой donor_url"})
            continue
        # Truncate to fit VARCHAR(512) on Postgres
        if len(url) > 512:
            url = url[:512]
        if url in seen_in_file:
            skipped += 1
            continue
        seen_in_file.add(url)

        link_type = (_to_str(row.get("link_type")) or "unknown").lower()[:32]
        # Normalise geo / language to canonical codes so the matcher can
        # compare "Spain" / "ES" / "España" as equal.
        raw_geo = _to_str(row.get("geo"))
        geo = normalize_country(raw_geo) or raw_geo[:64]
        if not geo:
            geo = country_from_url(url) or ""
        raw_lang = _to_str(row.get("language"))
        language = normalize_language(raw_lang) or raw_lang[:64]
        if not language:
            language = language_from_url(url) or ""
        payload = dict(
            donor_url=url,
            domain=extract_domain(url)[:255],
            tr=_to_float(row.get("tr")),
            organic_traffic=_to_int(row.get("organic_traffic")),
            ref_domains=_to_int(row.get("ref_domains")),
            backlinks=_to_int(row.get("backlinks")),
            geo=geo[:64],
            language=language[:64],
            link_type=link_type,
            category=_to_str(row.get("category"))[:128],
            comment=_to_str(row.get("comment")),
        )
        try:
            existing = db.query(Donor).filter(Donor.donor_url == url).one_or_none()
            if existing:
                for k, v in payload.items():
                    setattr(existing, k, v)
                updated += 1
            else:
                d = Donor(added_by=user_id, **payload)
                db.add(d)
                inserted += 1
            pending += 1
            if pending >= BATCH:
                # Commit each batch as its own transaction so a poison row
                # in batch N+1 can't undo the work of batches 1..N.
                try:
                    db.commit()
                    pending = 0
                except (IntegrityError, DataError) as e:
                    db.rollback()
                    failed += pending
                    inserted = max(0, inserted - pending)  # batch did not land
                    errors.append({"row": int(idx) + 2, "error": f"батч сброшен: {str(e.orig)[:150]}"})
                    pending = 0
        except Exception as e:
            db.rollback()
            failed += 1
            errors.append({"row": int(idx) + 2, "error": str(e)[:200]})
    # Final commit for the tail
    if pending:
        try:
            db.commit()
        except (IntegrityError, DataError) as e:
            db.rollback()
            failed += pending
            inserted = max(0, inserted - pending)
            errors.append({"row": "finalize", "error": str(e.orig)[:200]})

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
    # English
    "url": "target_url",
    "page": "target_url",
    "target_url": "target_url",
    "target": "target_url",
    "link": "target_url",
    "domain": "target_domain",
    "target_domain": "target_domain",
    "anchor": "anchor_text",
    "anchortext": "anchor_text",
    "anchor_text": "anchor_text",
    "geo": "geo",
    "country": "geo",
    "lang": "language",
    "language": "language",
    "type": "required_link_type",
    "link_type": "required_link_type",
    "linktype": "required_link_type",
    "required_link_type": "required_link_type",
    "requirement": "requirements",
    "requirements": "requirements",
    "notes": "requirements",
    # Russian — normalized headers like "Целевая ссылка" -> "целевая_ссылка"
    "целевая_ссылка": "target_url",
    "ссылка": "target_url",
    "url_страницы": "target_url",
    "адрес": "target_url",
    "страница": "target_url",
    "наша_ссылка": "target_url",
    "наш_url": "target_url",
    "продвигаемый_url": "target_url",
    "продвигаемая_ссылка": "target_url",
    "продвигаемая_страница": "target_url",
    "целевой_url": "target_url",
    "домен": "target_domain",
    "наш_домен": "target_domain",
    "продвигаемый_домен": "target_domain",
    "анкор": "anchor_text",
    "текст_анкора": "anchor_text",
    "якорь": "anchor_text",
    "ключ": "anchor_text",
    "ключевое_слово": "anchor_text",
    "гео": "geo",
    "страна": "geo",
    "регион": "geo",
    "язык": "language",
    "тип": "required_link_type",
    "тип_ссылки": "required_link_type",
    "требования": "requirements",
    "комментарий": "requirements",
    "примечание": "requirements",
}


def import_anchor_plan(
    db: Session,
    file_bytes: bytes,
    filename: str,
    plan_name: str,
    user_id: Optional[int],
    kind: str = "internal",
    client_project_id: Optional[int] = None,
) -> dict:
    df = _apply_synonyms(_read_table(file_bytes, filename), PLAN_SYNONYMS)
    if "target_url" not in df.columns and "target_domain" not in df.columns:
        raise ValueError("В файле нет обязательной колонки 'target_url' (или domain/url/target)")

    plan = AnchorPlan(
        plan_name=plan_name or filename or "Анкор-план",
        uploaded_file_name=filename,
        created_by=user_id,
        kind=kind or "internal",
        client_project_id=client_project_id,
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
            # GEO / language: respect the file's value if present, else infer
            # from the URL's TLD (.es → ES, .co.in → IN, etc.).
            raw_geo = _to_str(row.get("geo"))
            geo = normalize_country(raw_geo) or raw_geo.upper()[:64] if raw_geo else (country_from_url(target_url) or country_from_url(target_domain) or "")
            raw_lang = _to_str(row.get("language"))
            language = normalize_language(raw_lang) or raw_lang.lower()[:64] if raw_lang else (language_from_url(target_url) or language_from_url(target_domain) or "")
            item = AnchorPlanItem(
                anchor_plan_id=plan.id,
                target_url=target_url,
                target_domain=target_domain,
                anchor_text=_to_str(row.get("anchor_text")),
                geo=geo,
                language=language,
                required_link_type=(_to_str(row.get("required_link_type")) or "").lower(),
                requirements=_to_str(row.get("requirements")),
                status="new",
                kind=kind or "internal",
                client_project_id=client_project_id,
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
    # English
    "url": "target_url",
    "page": "target_url",
    "target_url": "target_url",
    "target": "target_url",
    "domain": "target_domain",
    "target_domain": "target_domain",
    "donor": "donor_url",
    "donor_url": "donor_url",
    "donor_site": "donor_url",
    "donor_link": "donor_url",
    "placed": "placed_at",
    "placed_at": "placed_at",
    "date": "placed_at",
    "result": "result_url",
    "result_url": "result_url",
    "result_link": "result_url",
    "notes": "comment",
    "comment": "comment",
    # Russian
    "целевая_ссылка": "target_url",
    "ссылка": "target_url",
    "наша_ссылка": "target_url",
    "домен": "target_domain",
    "донор": "donor_url",
    "url_донора": "donor_url",
    "дата": "placed_at",
    "размещено": "placed_at",
    "результат": "result_url",
    "ссылка_на_результат": "result_url",
    "комментарий": "comment",
    "примечание": "comment",
}


def _domainish(value: str) -> str:
    """Return the bare domain of `value` only if it really looks like a domain
    (a dot-bearing host). Keeps the permissive matrix parser from turning an
    unrelated table (labels, numbers, free text) into bogus stop-list rows.
    """
    d = extract_domain(value)
    return d if ("." in d and len(d) >= 4) else ""


def _read_matrix_raw(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """Read a sheet WITHOUT treating row 1 as a header, preserving exact cell
    values. Used for the 'matrix' stop-list layout, where the top row holds the
    target (brand) domains and each column below lists that brand's used donors.
    """
    name = (filename or "").lower()
    bio = io.BytesIO(file_bytes)
    if name.endswith(".xlsx") or name.endswith(".xls"):
        df = pd.read_excel(bio, dtype=object, header=None)
    else:
        try:
            df = pd.read_csv(bio, dtype=object, header=None)
        except UnicodeDecodeError:
            bio.seek(0)
            df = pd.read_csv(bio, dtype=object, header=None, encoding="cp1251")
    return df.where(pd.notnull(df), None)


def _stoplist_pairs_matrix(file_bytes: bytes, filename: str) -> list[dict]:
    """Parse the matrix layout into (target, donor) pairs.

    Row 0 = target/brand domains (one per column). Rows below = donor domains
    already used for that brand. Blank cells are skipped; columns may have
    different lengths. Everything is normalised to bare domains so it lines up
    with how the auto-matcher compares donors and targets.
    """
    df = _read_matrix_raw(file_bytes, filename)
    if df.shape[0] < 2 or df.shape[1] < 1:
        return []
    pairs: list[dict] = []
    for j in range(df.shape[1]):
        tdom = _domainish(_to_str(df.iat[0, j]))
        if not tdom:
            continue
        for i in range(1, df.shape[0]):
            cell = _to_str(df.iat[i, j])
            if not cell:
                continue
            ddom = _domainish(cell)
            if not ddom:
                continue
            pairs.append({
                "target_url": tdom,        # bare domain => brand/domain-level entry
                "target_domain": tdom,
                "donor_url": ddom,
                "anchor_text": "",
                "result_url": "",
                "comment": "",
                "row": i + 1,
            })
    return pairs


def _stoplist_pairs_long(df: pd.DataFrame) -> list[dict]:
    """Parse the classic long layout (donor_url + target_url/target_domain)."""
    pairs: list[dict] = []
    for idx, row in df.iterrows():
        target_url = _to_str(row.get("target_url"))
        target_domain = _to_str(row.get("target_domain")) or extract_domain(target_url)
        pairs.append({
            # fall back to the domain so the UNIQUE constraint still works
            "target_url": target_url or target_domain,
            "target_domain": target_domain or extract_domain(target_url),
            "donor_url": _to_str(row.get("donor_url")),
            "anchor_text": "",
            "result_url": _to_str(row.get("result_url")),
            "comment": _to_str(row.get("comment")),
            "row": int(idx) + 2,
        })
    return pairs


def _stoplist_is_long(df: pd.DataFrame) -> bool:
    return "donor_url" in df.columns and ("target_url" in df.columns or "target_domain" in df.columns)


def import_stop_list(db: Session, file_bytes: bytes, filename: str, user_id: Optional[int]) -> dict:
    # Detect the layout. A classic 'long' file has recognisable headers
    # (donor_url + target_url/target_domain); anything else is treated as the
    # 'matrix' layout (brand domains across the top row, donors listed below).
    try:
        df_long = _apply_synonyms(_read_table(file_bytes, filename), STOPLIST_SYNONYMS)
    except Exception:
        df_long = None

    if df_long is not None and _stoplist_is_long(df_long):
        pairs = _stoplist_pairs_long(df_long)
    else:
        pairs = _stoplist_pairs_matrix(file_bytes, filename)
        if not pairs:
            raise ValueError(
                "Не удалось распознать стоп-лист. Нужен либо файл с колонками "
                "'donor_url' и 'target_url'/'target_domain', либо матрица: в верхней "
                "строке — целевые домены, под каждым столбцом — доноры."
            )

    # Preload donor id lookups (by full url and by domain) so matrix rows that
    # carry bare domains still link to an existing donor.
    donor_by_url = dict(db.query(Donor.donor_url, Donor.id).all())
    donor_by_domain = {d: i for d, i in db.query(Donor.domain, Donor.id).all() if d}

    # Preload existing (target_url, donor_url) pairs for the targets in this file
    # so we can dedupe without a query per row.
    target_urls = [t for t in {p["target_url"] for p in pairs if p["target_url"]}]
    existing: set[tuple] = set()
    for k in range(0, len(target_urls), 500):
        chunk = target_urls[k:k + 500]
        for tu, du in db.query(StopListEntry.target_url, StopListEntry.donor_url).filter(
            StopListEntry.target_url.in_(chunk)
        ).all():
            existing.add((tu, du))

    errors: list[dict] = []
    inserted = skipped = failed = 0
    seen: set[tuple] = set()
    for p in pairs:
        donor_url = p["donor_url"]
        target_url = p["target_url"]
        target_domain = p["target_domain"] or extract_domain(target_url)
        if not donor_url or not target_url:
            failed += 1
            errors.append({"row": p.get("row"), "error": "пустой donor или target"})
            continue
        key = (target_url, donor_url)
        if key in existing or key in seen:
            skipped += 1
            continue
        seen.add(key)
        donor_id = donor_by_url.get(donor_url) or donor_by_domain.get(extract_domain(donor_url))
        entry = StopListEntry(
            target_url=target_url,
            target_domain=target_domain,
            donor_url=donor_url,
            donor_id=donor_id,
            anchor_text=p.get("anchor_text", ""),
            result_url=p.get("result_url", ""),
            comment=p.get("comment", ""),
            placed_by=user_id,
            source_anchor_plan="(импортировано)",
        )
        db.add(entry)
        inserted += 1

    total = len(pairs)
    log = ImportLog(
        type="stop_list",
        file_name=filename,
        rows_total=total,
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
        "rows_total": total,
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
