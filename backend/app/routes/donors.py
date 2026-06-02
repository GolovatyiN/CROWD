from typing import Optional
import io

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_admin
from ..database import get_db
from ..models import Donor, DonorAccount, Placement, StopListEntry, User
from ..schemas import (
    DonorAccountCreate,
    DonorAccountOut,
    DonorAccountUpdate,
    DonorCreate,
    DonorOut,
    DonorUpdate,
    ImportPreview,
)
from ..services.importer import donors_to_csv, import_donors
from ..services.matcher import account_usage, extract_domain, invalidate_donor_cache
from ..services.geo import normalize_country, normalize_language

router = APIRouter(prefix="/donors", tags=["donors"])


SORT_FIELDS = {
    "domain": Donor.domain,
    "donor_url": Donor.donor_url,
    "tr": Donor.tr,
    "dr": Donor.tr,
    "organic_traffic": Donor.organic_traffic,
    "ref_domains": Donor.ref_domains,
    "backlinks": Donor.backlinks,
    "geo": Donor.geo,
    "language": Donor.language,
    "link_type": Donor.link_type,
    "status": Donor.status,
    "updated_at": Donor.updated_at,
    "created_at": Donor.created_at,
    "id": Donor.id,
}


def _apply_donor_filters(query, *, q, geo, language, link_type, min_tr, min_traffic, min_ref_domains, min_backlinks, status, is_active, used, db):
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(or_(func.lower(Donor.donor_url).like(like), func.lower(Donor.domain).like(like)))
    if geo:
        query = query.filter(func.lower(Donor.geo) == geo.lower())
    if language:
        query = query.filter(func.lower(Donor.language) == language.lower())
    if link_type:
        query = query.filter(func.lower(Donor.link_type) == link_type.lower())
    if min_tr is not None:
        query = query.filter(Donor.tr >= min_tr)
    if min_traffic is not None:
        query = query.filter(Donor.organic_traffic >= min_traffic)
    if min_ref_domains is not None:
        query = query.filter(Donor.ref_domains >= min_ref_domains)
    if min_backlinks is not None:
        query = query.filter(Donor.backlinks >= min_backlinks)
    if status:
        query = query.filter(Donor.status == status)
    if is_active is not None:
        query = query.filter(Donor.is_active.is_(is_active))
    if used is True:
        sub = db.query(StopListEntry.donor_url).distinct()
        query = query.filter(Donor.donor_url.in_(sub))
    elif used is False:
        sub = db.query(StopListEntry.donor_url).distinct()
        query = query.filter(~Donor.donor_url.in_(sub))
    return query


@router.get("")
def list_donors(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
    q: Optional[str] = None,
    geo: Optional[str] = None,
    language: Optional[str] = None,
    link_type: Optional[str] = None,
    min_tr: Optional[float] = None,
    min_traffic: Optional[int] = None,
    min_ref_domains: Optional[int] = None,
    min_backlinks: Optional[int] = None,
    status: Optional[str] = None,
    is_active: Optional[bool] = None,
    used: Optional[bool] = Query(None),
    sort: str = "tr",
    order: str = "desc",
    limit: int = 100,
    offset: int = 0,
):
    base = db.query(Donor)
    base = _apply_donor_filters(
        base, q=q, geo=geo, language=language, link_type=link_type,
        min_tr=min_tr, min_traffic=min_traffic, min_ref_domains=min_ref_domains,
        min_backlinks=min_backlinks, status=status, is_active=is_active,
        used=used, db=db,
    )
    total = base.with_entities(func.count(Donor.id)).scalar() or 0

    sort_col = SORT_FIELDS.get(sort.lower(), Donor.tr)
    base = base.order_by(sort_col.desc() if order.lower() == "desc" else sort_col.asc(), Donor.id.desc())

    items = base.offset(offset).limit(min(limit, 500)).all()
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [DonorOut.model_validate(d).model_dump(mode="json") for d in items],
    }


@router.post("", response_model=DonorOut)
def create_donor(payload: DonorCreate, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    if db.query(Donor).filter(Donor.donor_url == payload.donor_url).first():
        raise HTTPException(status_code=400, detail="Донор с таким URL уже существует")
    donor = Donor(
        **payload.model_dump(),
        domain=extract_domain(payload.donor_url),
        added_by=user.id,
    )
    db.add(donor)
    db.commit()
    db.refresh(donor)
    invalidate_donor_cache()  # new donor must be visible to the matcher at once
    return donor


@router.patch("/{donor_id}", response_model=DonorOut)
def update_donor(donor_id: int, payload: DonorUpdate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    donor = db.get(Donor, donor_id)
    if not donor:
        raise HTTPException(status_code=404, detail="Донор не найден")
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(donor, k, v)
    if "donor_url" in data:
        donor.domain = extract_domain(donor.donor_url)
    db.commit()
    db.refresh(donor)
    invalidate_donor_cache()  # geo/lang/active changes affect matching
    return donor


@router.delete("/{donor_id}")
def deactivate_donor(donor_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    donor = db.get(Donor, donor_id)
    if not donor:
        raise HTTPException(status_code=404, detail="Донор не найден")
    donor.is_active = False
    db.commit()
    invalidate_donor_cache()
    return {"ok": True}


@router.post("/bulk-deactivate")
def bulk_deactivate(payload: dict = Body(...), db: Session = Depends(get_db), _: User = Depends(require_admin)):
    ids = payload.get("ids") or []
    if not ids:
        raise HTTPException(status_code=400, detail="Передайте список ids")
    updated = db.query(Donor).filter(Donor.id.in_(ids)).update({Donor.is_active: False}, synchronize_session=False)
    db.commit()
    invalidate_donor_cache()
    return {"updated": updated}


@router.post("/bulk-activate")
def bulk_activate(payload: dict = Body(...), db: Session = Depends(get_db), _: User = Depends(require_admin)):
    ids = payload.get("ids") or []
    if not ids:
        raise HTTPException(status_code=400, detail="Передайте список ids")
    updated = db.query(Donor).filter(Donor.id.in_(ids)).update({Donor.is_active: True}, synchronize_session=False)
    db.commit()
    invalidate_donor_cache()
    return {"updated": updated}


@router.get("/stats")
def donors_stats(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Quick health-check of the donor pool — counts per GEO / language /
    link_type. Helps the admin see why the matcher might say 'no GEO=SK
    donors': they can verify their base really has no Slovak donors.
    """
    total = db.query(func.count(Donor.id)).scalar() or 0
    active = db.query(func.count(Donor.id)).filter(Donor.is_active.is_(True)).scalar() or 0

    # Build distributions with the same normalisation the matcher uses.
    geo_counts: dict[str, int] = {}
    lang_counts: dict[str, int] = {}
    link_counts: dict[str, int] = {}
    rows = db.execute(
        select(Donor.geo, Donor.language, Donor.link_type).where(Donor.is_active.is_(True))
    ).all()
    for g, l, t in rows:
        gn = normalize_country(g or "") or "(не указано)"
        ln = normalize_language(l or "") or "(не указано)"
        tn = (t or "unknown").lower()
        geo_counts[gn] = geo_counts.get(gn, 0) + 1
        lang_counts[ln] = lang_counts.get(ln, 0) + 1
        link_counts[tn] = link_counts.get(tn, 0) + 1

    def sort_dict(d: dict[str, int]) -> list[dict]:
        return [{"key": k, "count": v} for k, v in sorted(d.items(), key=lambda kv: kv[1], reverse=True)]

    return {
        "total": total,
        "active": active,
        "by_geo": sort_dict(geo_counts),
        "by_language": sort_dict(lang_counts),
        "by_link_type": sort_dict(link_counts),
    }


@router.get("/{donor_id}/usage")
def donor_usage(donor_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    donor = db.get(Donor, donor_id)
    if not donor:
        raise HTTPException(status_code=404, detail="Донор не найден")
    placements = (
        db.query(Placement).filter(Placement.donor_id == donor_id).order_by(Placement.created_at.desc()).limit(200).all()
    )
    return {
        "donor": DonorOut.model_validate(donor).model_dump(mode="json"),
        "placements": [
            {
                "id": p.id,
                "target_url": p.target_url,
                "result_url": p.result_url,
                "status": p.status,
                "placed_at": p.placed_at.isoformat() if p.placed_at else None,
                "employee_id": p.employee_id,
            }
            for p in placements
        ],
    }


# ---- accounts ----

def _account_out(acc: DonorAccount, usage_map: dict[int, int]) -> dict:
    d = DonorAccountOut.model_validate(acc).model_dump(mode="json")
    d["usage_count"] = usage_map.get(acc.id, 0)
    return d


@router.get("/{donor_id}/accounts")
def list_accounts(donor_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    accounts = db.query(DonorAccount).filter(DonorAccount.donor_id == donor_id).order_by(DonorAccount.id.asc()).all()
    usage_map = account_usage(db, donor_id)
    return [_account_out(a, usage_map) for a in accounts]


@router.post("/{donor_id}/accounts")
def create_account(
    donor_id: int,
    payload: DonorAccountCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    if payload.donor_id != donor_id:
        raise HTTPException(status_code=400, detail="donor_id не совпадает")
    donor = db.get(Donor, donor_id)
    if not donor:
        raise HTTPException(status_code=404, detail="Донор не найден")
    if payload.account_username:
        dup = (
            db.query(DonorAccount)
            .filter(DonorAccount.donor_id == donor_id, DonorAccount.account_username == payload.account_username)
            .first()
        )
        if dup:
            raise HTTPException(status_code=400, detail="Аккаунт с таким именем уже есть у этого донора")
    account = DonorAccount(
        donor_id=donor_id,
        login_email=payload.login_email,
        login_password=payload.login_password,
        account_username=payload.account_username,
        comment=payload.comment,
        is_active=payload.is_active,
        max_placements=payload.max_placements or 0,
        created_by=user.id,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return _account_out(account, account_usage(db, donor_id))


@router.patch("/{donor_id}/accounts/{account_id}")
def update_account(
    donor_id: int,
    account_id: int,
    payload: DonorAccountUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    account = db.get(DonorAccount, account_id)
    if not account or account.donor_id != donor_id:
        raise HTTPException(status_code=404, detail="Аккаунт не найден")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(account, k, v)
    db.commit()
    db.refresh(account)
    return _account_out(account, account_usage(db, donor_id))


@router.delete("/{donor_id}/accounts/{account_id}")
def delete_account(
    donor_id: int,
    account_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    account = db.get(DonorAccount, account_id)
    if not account or account.donor_id != donor_id:
        raise HTTPException(status_code=404, detail="Аккаунт не найден")
    db.delete(account)
    db.commit()
    return {"ok": True}


# ---- import / export ----

@router.post("/import", response_model=ImportPreview)
async def import_donors_route(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Файл пустой")
    try:
        result = import_donors(db, content, file.filename or "donors", user.id)
        db.commit()
        invalidate_donor_cache()
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        # Surface the underlying error rather than letting it become a 500.
        msg = str(e).splitlines()[0][:300] if str(e) else type(e).__name__
        raise HTTPException(status_code=400, detail=f"Не удалось обработать файл: {msg}")
    return result


@router.get("/export")
def export_donors(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    donors = db.query(Donor).order_by(Donor.id.asc()).all()
    csv_data = donors_to_csv(donors)
    return StreamingResponse(
        io.BytesIO(csv_data.encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="donors.csv"'},
    )
