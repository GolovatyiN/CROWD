from datetime import datetime
from sqlalchemy import (
    String, Integer, BigInteger, Float, Boolean, DateTime, Text, ForeignKey,
    UniqueConstraint, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..database import Base


def utcnow() -> datetime:
    return datetime.utcnow()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    role: Mapped[str] = mapped_column(String(32), default="employee")  # admin | employee
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Donor(Base):
    __tablename__ = "donors"

    id: Mapped[int] = mapped_column(primary_key=True)
    donor_url: Mapped[str] = mapped_column(String(512), unique=True, index=True, nullable=False)
    domain: Mapped[str] = mapped_column(String(255), index=True, default="")
    tr: Mapped[float] = mapped_column(Float, default=0)
    # Top sites (wikipedia, pinterest, etc.) have billions of backlinks and
    # hundreds of millions of organic visits — overflow int4 on Postgres.
    organic_traffic: Mapped[int] = mapped_column(BigInteger, default=0)
    ref_domains: Mapped[int] = mapped_column(BigInteger, default=0)
    backlinks: Mapped[int] = mapped_column(BigInteger, default=0)
    geo: Mapped[str] = mapped_column(String(64), default="", index=True)
    language: Mapped[str] = mapped_column(String(64), default="", index=True)
    link_type: Mapped[str] = mapped_column(String(32), default="unknown")  # dofollow|nofollow|mixed|unknown
    category: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(32), default="active")
    comment: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    added_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    accounts: Mapped[list["DonorAccount"]] = relationship(back_populates="donor", cascade="all, delete-orphan")


class DonorAccount(Base):
    __tablename__ = "donor_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    donor_id: Mapped[int] = mapped_column(ForeignKey("donors.id", ondelete="CASCADE"), nullable=False, index=True)
    login_email: Mapped[str] = mapped_column(String(255), default="")
    login_password: Mapped[str] = mapped_column(String(255), default="")
    account_username: Mapped[str] = mapped_column(String(255), default="")
    comment: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Optional cap: how many placements can be made from this account.
    # 0 / NULL means "no limit".
    max_placements: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    donor: Mapped[Donor] = relationship(back_populates="accounts")

    __table_args__ = (
        UniqueConstraint("donor_id", "account_username", name="uq_donor_account_username"),
    )


class AnchorPlan(Base):
    __tablename__ = "anchor_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_name: Mapped[str] = mapped_column(String(255), nullable=False)
    uploaded_file_name: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    items: Mapped[list["AnchorPlanItem"]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class AnchorPlanItem(Base):
    __tablename__ = "anchor_plan_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    anchor_plan_id: Mapped[int] = mapped_column(ForeignKey("anchor_plans.id", ondelete="CASCADE"), index=True)
    target_domain: Mapped[str] = mapped_column(String(255), index=True, default="")
    target_url: Mapped[str] = mapped_column(String(1024), index=True, default="")
    anchor_text: Mapped[str] = mapped_column(String(512), default="")
    geo: Mapped[str] = mapped_column(String(64), default="")
    language: Mapped[str] = mapped_column(String(64), default="")
    required_link_type: Mapped[str] = mapped_column(String(32), default="")
    requirements: Mapped[str] = mapped_column(Text, default="")
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    selected_donor_id: Mapped[int | None] = mapped_column(ForeignKey("donors.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="new", index=True)
    result_url: Mapped[str] = mapped_column(String(1024), default="")
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    plan: Mapped[AnchorPlan] = relationship(back_populates="items")


class Placement(Base):
    __tablename__ = "placements"

    id: Mapped[int] = mapped_column(primary_key=True)
    anchor_plan_item_id: Mapped[int | None] = mapped_column(ForeignKey("anchor_plan_items.id"), nullable=True, index=True)
    target_domain: Mapped[str] = mapped_column(String(255), index=True, default="")
    target_url: Mapped[str] = mapped_column(String(1024), index=True, default="")
    donor_id: Mapped[int | None] = mapped_column(ForeignKey("donors.id"), nullable=True, index=True)
    donor_url: Mapped[str] = mapped_column(String(512), index=True, default="")
    anchor_text: Mapped[str] = mapped_column(String(512), default="")
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    donor_account_id: Mapped[int | None] = mapped_column(ForeignKey("donor_accounts.id"), nullable=True)
    result_url: Mapped[str] = mapped_column(String(1024), default="")
    status: Mapped[str] = mapped_column(String(32), default="in_progress", index=True)
    login_email: Mapped[str] = mapped_column(String(255), default="")
    login_password: Mapped[str] = mapped_column(String(255), default="")
    account_username: Mapped[str] = mapped_column(String(255), default="")
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    placed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class StopListEntry(Base):
    __tablename__ = "stop_list_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    target_domain: Mapped[str] = mapped_column(String(255), index=True, default="")
    target_url: Mapped[str] = mapped_column(String(1024), index=True, nullable=False)
    donor_id: Mapped[int | None] = mapped_column(ForeignKey("donors.id"), nullable=True, index=True)
    donor_url: Mapped[str] = mapped_column(String(512), index=True, nullable=False)
    anchor_plan_item_id: Mapped[int | None] = mapped_column(ForeignKey("anchor_plan_items.id"), nullable=True)
    placed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    placed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    result_url: Mapped[str] = mapped_column(String(1024), default="")
    anchor_text: Mapped[str] = mapped_column(String(512), default="")
    account_username: Mapped[str] = mapped_column(String(255), default="")
    login_email: Mapped[str] = mapped_column(String(255), default="")
    source_anchor_plan: Mapped[str] = mapped_column(String(255), default="")
    comment: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (
        UniqueConstraint("target_url", "donor_url", name="uq_stoplist_url_donor"),
        Index("ix_stoplist_target_donor", "target_url", "donor_url"),
    )


class ImportLog(Base):
    __tablename__ = "import_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(32))  # donors | anchor_plan | stop_list
    file_name: Mapped[str] = mapped_column(String(512), default="")
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_inserted: Mapped[int] = mapped_column(Integer, default=0)
    rows_updated: Mapped[int] = mapped_column(Integer, default=0)
    rows_skipped: Mapped[int] = mapped_column(Integer, default=0)
    rows_failed: Mapped[int] = mapped_column(Integer, default=0)
    errors_json: Mapped[str] = mapped_column(Text, default="[]")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    """Append-only journal of sensitive admin actions.

    Currently scoped to user management — role changes, activation toggles,
    password resets, etc. Easy to widen later to donors / plans if needed.
    """
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    actor_email: Mapped[str] = mapped_column(String(255), default="")
    action: Mapped[str] = mapped_column(String(64), index=True)  # user.create, user.role_change, ...
    target_type: Mapped[str] = mapped_column(String(32), default="user")
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    target_label: Mapped[str] = mapped_column(String(255), default="")
    details: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
