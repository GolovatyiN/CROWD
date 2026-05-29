"""One-off cleanup: wipe operational data, keep only the named super-admin.

Run with the production DATABASE_URL in the environment:
    DATABASE_URL='...' KEEP_EMAIL='you@example.com' python -m scripts.wipe_data
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import text

# Allow `python -m scripts.wipe_data` to find `app/`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, engine, DATABASE_URL  # noqa: E402
from app.models import User  # noqa: E402


KEEP_EMAIL = os.environ.get("KEEP_EMAIL", "").strip().lower()


def main() -> None:
    if not KEEP_EMAIL:
        print("ERROR: set KEEP_EMAIL env var to the super-admin you want to keep.")
        sys.exit(2)

    print(f"Target DB: {DATABASE_URL.split('@', 1)[-1].split('?', 1)[0]}")
    print(f"Will keep user: {KEEP_EMAIL!r}")

    db = SessionLocal()
    try:
        keep = db.query(User).filter(User.email.ilike(KEEP_EMAIL)).first()
        if not keep:
            print(f"ERROR: no user with email {KEEP_EMAIL!r} exists. Aborting.")
            sys.exit(2)
        if keep.role != "super_admin" or not keep.is_active:
            keep.role = "super_admin"
            keep.is_active = True
            db.commit()
            print("(promoted keep user to active super_admin)")

        # Order matters — wipe FK-dependent tables first.
        # Use raw SQL so we don't have to load ORM rows for thousands of records.
        TABLES_IN_ORDER = [
            "stop_list_entries",
            "placements",
            "anchor_plan_items",
            "anchor_plans",
            "donor_accounts",
            "donors",
            "import_logs",
            "audit_logs",
        ]
        for table in TABLES_IN_ORDER:
            res = db.execute(text(f"DELETE FROM {table}"))
            print(f"  {table:24} deleted {res.rowcount} rows")

        # Wipe other users.
        res = db.execute(
            text("DELETE FROM users WHERE id <> :keep_id"),
            {"keep_id": keep.id},
        )
        print(f"  {'users (other)':24} deleted {res.rowcount} rows")

        db.commit()

        # Reset sequences on Postgres so new IDs start at 1.
        if engine.dialect.name == "postgresql":
            print("Resetting sequences…")
            for table in TABLES_IN_ORDER + ["users"]:
                try:
                    db.execute(text(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE((SELECT MAX(id) FROM {table}), 1))"))
                except Exception as e:
                    print(f"  {table:24} sequence reset skipped: {e}")
            db.commit()

        # Sanity check
        for table in TABLES_IN_ORDER + ["users"]:
            count = db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            print(f"  {table:24} now has {count} rows")

        print(f"\nDONE. Kept super-admin: {keep.email} (id={keep.id})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
