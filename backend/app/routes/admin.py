"""Admin-only maintenance actions.

Currently a single 'reset all operational data' action — wipes donors, plans,
placements, the stop-list and email accounts so the dashboard goes back to
zero, without touching the user roster or the audit journal (we keep the
record that the reset happened, and who did it).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import require_super_admin
from ..database import get_db
from ..models import (
    AnchorPlan,
    AnchorPlanItem,
    Donor,
    DonorAccount,
    EmailAccount,
    ImportLog,
    Placement,
    StopListEntry,
    User,
)
from ..services import audit
from ..services.matcher import invalidate_donor_cache

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/reset-data")
def reset_data(db: Session = Depends(get_db), actor: User = Depends(require_super_admin)):
    """Hard-delete all operational data. Super-Admin only.

    Keeps `users` (so you stay logged in) and `audit_logs` (so the reset is
    recorded). Children are removed before parents to avoid FK violations.
    """
    counts = {
        "placements": db.query(Placement).count(),
        "stop_list": db.query(StopListEntry).count(),
        "plan_items": db.query(AnchorPlanItem).count(),
        "plans": db.query(AnchorPlan).count(),
        "donor_accounts": db.query(DonorAccount).count(),
        "donors": db.query(Donor).count(),
        "email_accounts": db.query(EmailAccount).count(),
    }

    # Order matters: delete rows that reference others first.
    db.query(Placement).delete(synchronize_session=False)
    db.query(StopListEntry).delete(synchronize_session=False)
    db.query(AnchorPlanItem).delete(synchronize_session=False)
    db.query(AnchorPlan).delete(synchronize_session=False)
    db.query(DonorAccount).delete(synchronize_session=False)
    db.query(Donor).delete(synchronize_session=False)
    db.query(EmailAccount).delete(synchronize_session=False)
    db.query(ImportLog).delete(synchronize_session=False)

    audit.log(
        db, actor, "system.reset",
        target_type="system",
        target_label="вся система",
        доноров=counts["donors"],
        планов=counts["plans"],
        размещений=counts["placements"],
        стоп_лист=counts["stop_list"],
        аккаунтов=counts["email_accounts"],
    )
    db.commit()
    invalidate_donor_cache()
    return {"ok": True, "deleted": counts}
