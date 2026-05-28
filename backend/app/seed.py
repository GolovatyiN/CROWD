"""Seed admin + demo data.

Run with: python -m app.seed
"""

from __future__ import annotations

from .auth import hash_password
from .config import settings
from .database import SessionLocal
from .models import (
    AnchorPlan,
    AnchorPlanItem,
    Donor,
    User,
)
from .services.matcher import extract_domain


DEMO_EMPLOYEES = [
    ("nastya@crowd.local", "Настя"),
    ("andrey@crowd.local", "Андрей"),
    ("artem@crowd.local", "Артём"),
]

DEMO_DONORS = [
    # url, tr, traffic, ref_domains, backlinks, geo, language, link_type
    ("https://forum.example.com/", 45, 120000, 4500, 90000, "US", "en", "dofollow"),
    ("https://board.example.de/", 38, 60000, 2200, 30000, "DE", "de", "nofollow"),
    ("https://community.example.fr/", 30, 45000, 1500, 20000, "FR", "fr", "mixed"),
    ("https://forum.test-ua.com/", 25, 30000, 900, 11000, "UA", "uk", "dofollow"),
    ("https://blog.example.es/", 52, 200000, 8000, 130000, "ES", "es", "dofollow"),
    ("https://news.example.it/", 41, 95000, 3300, 70000, "IT", "it", "mixed"),
    ("https://forum.eng-global.com/", 60, 500000, 12000, 250000, "US", "en", "dofollow"),
    ("https://board.spam.net/", 5, 1000, 50, 200, "", "", "nofollow"),
]

DEMO_PLAN_ITEMS = [
    # target_url, anchor, geo, language, required_link_type
    ("https://mybrand.com/page-1", "best service", "US", "en", "dofollow"),
    ("https://mybrand.com/page-2", "buy now", "US", "en", ""),
    ("https://mybrand.com/de", "kaufen", "DE", "de", ""),
    ("https://mybrand.com/es", "comprar ahora", "ES", "es", "dofollow"),
    ("https://mybrand.com/it", "scopri di piu", "IT", "it", ""),
    ("https://mybrand.com/fr", "en savoir plus", "FR", "fr", ""),
]


def run() -> None:
    """Create admin user (idempotent). Demo data only seeded when SEED_DEMO=1."""
    import os
    db = SessionLocal()
    seed_demo = os.environ.get("SEED_DEMO", "1") == "1"
    try:
        # Admin
        if not db.query(User).filter(User.email == settings.admin_email).first():
            db.add(User(
                email=settings.admin_email,
                full_name=settings.admin_name,
                role="admin",
                password_hash=hash_password(settings.admin_password),
                is_active=True,
            ))
        db.commit()

        if not seed_demo:
            print(f"Seed OK (admin only). Login: {settings.admin_email}")
            return

        # Employees
        for email, name in DEMO_EMPLOYEES:
            if not db.query(User).filter(User.email == email).first():
                db.add(User(
                    email=email,
                    full_name=name,
                    role="employee",
                    password_hash=hash_password("employee123"),
                    is_active=True,
                ))

        # Donors
        for url, tr, traffic, ref_d, backlinks, geo, lang, lt in DEMO_DONORS:
            if db.query(Donor).filter(Donor.donor_url == url).first():
                continue
            db.add(Donor(
                donor_url=url,
                domain=extract_domain(url),
                tr=tr,
                organic_traffic=traffic,
                ref_domains=ref_d,
                backlinks=backlinks,
                geo=geo,
                language=lang,
                link_type=lt,
                status="active",
                is_active=True,
            ))

        # Plan
        plan = db.query(AnchorPlan).filter(AnchorPlan.plan_name == "Демо-план").first()
        if not plan:
            plan = AnchorPlan(plan_name="Демо-план", uploaded_file_name="demo.csv")
            db.add(plan)
            db.flush()
            for target_url, anchor, geo, lang, rlt in DEMO_PLAN_ITEMS:
                db.add(AnchorPlanItem(
                    anchor_plan_id=plan.id,
                    target_url=target_url,
                    target_domain=extract_domain(target_url),
                    anchor_text=anchor,
                    geo=geo,
                    language=lang,
                    required_link_type=rlt,
                    status="new",
                ))

        db.commit()
        print(f"Seed OK. Admin login: {settings.admin_email} / {settings.admin_password}")
        print("Employees (password 'employee123'):")
        for email, _ in DEMO_EMPLOYEES:
            print(f"  - {email}")
    finally:
        db.close()


if __name__ == "__main__":
    run()
