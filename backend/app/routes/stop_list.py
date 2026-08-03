from datetime import datetime
from typing import Optional
import io

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..auth import require_admin, require_staff
from ..database import get_db
from ..models import StopListEntry, User
from ..schemas import ImportPreview, StopListOut
from ..services import audit
from ..services.importer import import_stop_list, stop_list_to_csv

router = APIRouter(prefix="/stop-list", tags=["stop_list"])


SL_SORT_FIELDS = {
    "id": StopListEntry.id,
    "target_url": StopListEntry.target_url,
    "target_domain": StopListEntry.target_domain,
    "donor_url": StopListEntry.donor_url,
    "anchor_text": StopListEntry.anchor_text,
    "placed_at": StopListEntry.placed_at,
    "placed_by": StopListEntry.placed_by,
    "source_anchor_plan": StopListEntry.source_anchor_plan,
}


@router.get("", response_model=list[StopListOut])
def list_stop_list(
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
    q: Optional[str] = None,
    target_domain: Optional[str] = None,
    donor_url: Optional[str] = None,
    placed_by: Optional[int] = None,
    client_id: Optional[int] = None,
    client_project_id: Optional[int] = None,
    level: Optional[str] = None,
    source: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sort: str = "placed_at",
    order: str = "desc",
    limit: int = 500,
    offset: int = 0,
):
    query = db.query(StopListEntry)
    if client_id is not None:
        query = query.filter(StopListEntry.client_id == client_id)
    if client_project_id is not None:
        query = query.filter(StopListEntry.client_project_id == client_project_id)
    if level:
        query = query.filter(StopListEntry.level == level)
    if source:
        query = query.filter(StopListEntry.source == source)
    if status:
        query = query.filter(StopListEntry.status == status)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(or_(
            func.lower(StopListEntry.target_url).like(like),
            func.lower(StopListEntry.target_domain).like(like),
            func.lower(StopListEntry.donor_url).like(like),
        ))
    if target_domain:
        query = query.filter(func.lower(StopListEntry.target_domain) == target_domain.lower())
    if donor_url:
        query = query.filter(func.lower(StopListEntry.donor_url) == donor_url.lower())
    if placed_by is not None:
        query = query.filter(StopListEntry.placed_by == placed_by)
    if date_from:
        try:
            query = query.filter(StopListEntry.placed_at >= datetime.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            query = query.filter(StopListEntry.placed_at <= datetime.fromisoformat(date_to))
        except ValueError:
            pass
    sort_col = SL_SORT_FIELDS.get(sort.lower(), StopListEntry.placed_at)
    direction = sort_col.desc() if order.lower() == "desc" else sort_col.asc()
    return query.order_by(direction).offset(offset).limit(limit).all()


@router.post("/import", response_model=ImportPreview)
async def import_route(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    content = await file.read()
    try:
        result = import_stop_list(db, content, file.filename or "stop_list", user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    audit.log(
        db, user, "stoplist.import",
        target_label=file.filename or "стоп-лист",
        добавлено=getattr(result, "rows_inserted", 0),
    )
    db.commit()
    return result


@router.get("/export")
def export_route(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = db.query(StopListEntry).order_by(StopListEntry.placed_at.desc()).all()
    csv_data = stop_list_to_csv(rows)
    return StreamingResponse(
        io.BytesIO(csv_data.encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="stop_list.csv"'},
    )


@router.delete("/{entry_id}")
def delete_entry(entry_id: int, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    entry = db.get(StopListEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    audit.log(db, actor, "stoplist.delete", target_id=entry.id, target_label=entry.donor_url or "")
    db.delete(entry)
    db.commit()
    return {"ok": True}
