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
    role: Mapped[str] = mapped_column(String(32), default="user")  # super_admin|admin|manager|teamlead|user|client
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Set only for role='client' — that user sees only this client's data.
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True)
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
    # Which mailbox from the shared pool (EmailAccount) this donor-account uses.
    # Links the pool ↔ donor usage so we can see which mailbox served which donor
    # and reuse it on repeat placements. NULL = mailbox not (yet) in the pool.
    email_account_id: Mapped[int | None] = mapped_column(ForeignKey("email_accounts.id", ondelete="SET NULL"), nullable=True, index=True)
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
    # internal | client — 'internal' = наши проекты, 'client' = для внешних клиентов.
    # Denormalised onto items/placements/stop-list (inherited from the plan).
    kind: Mapped[str] = mapped_column(String(16), default="internal", server_default="internal", nullable=False, index=True)
    # Set for client plans (kind='client'); NULL for internal plans.
    client_project_id: Mapped[int | None] = mapped_column(ForeignKey("client_projects.id", ondelete="SET NULL"), nullable=True, index=True)
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
    kind: Mapped[str] = mapped_column(String(16), default="internal", server_default="internal", nullable=False, index=True)  # inherited from plan
    client_project_id: Mapped[int | None] = mapped_column(ForeignKey("client_projects.id", ondelete="SET NULL"), nullable=True, index=True)  # inherited from plan
    # Aggregate ("Формат 2": анкор + количество). A bucket item has
    # required_count > 1 and lazily spawns child unit-items (parent_item_id set)
    # in batches instead of materialising tens of thousands of identical rows.
    # Standalone Format-1 items keep required_count=1 and no parent.
    #   remaining = required_count - reserved_count - used_count
    required_count: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    reserved_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    used_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    parent_item_id: Mapped[int | None] = mapped_column(ForeignKey("anchor_plan_items.id", ondelete="CASCADE"), nullable=True, index=True)
    anchor_type: Mapped[str] = mapped_column(String(32), default="", server_default="")  # exact|partial|branded|url|unanchored|generic|image|custom|...
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False, index=True)
    result_url: Mapped[str] = mapped_column(String(1024), default="")
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    plan: Mapped[AnchorPlan] = relationship(back_populates="items")

    # Composite indexes for the two hot aggregations over this (largest) table:
    # per-plan status counts and the my-tasks view. See migration c3d4e5f6a7b8.
    __table_args__ = (
        Index("ix_api_plan_status", "anchor_plan_id", "status"),
        Index("ix_api_assigned_status", "assigned_to", "status"),
    )


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
    kind: Mapped[str] = mapped_column(String(16), default="internal", server_default="internal", nullable=False, index=True)  # inherited from item/plan
    # Denormalised client links (NULL for internal) — client portal isolation
    # filters directly on client_id, so it must live on the placement itself.
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True)
    client_project_id: Mapped[int | None] = mapped_column(ForeignKey("client_projects.id", ondelete="SET NULL"), nullable=True, index=True)
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
    kind: Mapped[str] = mapped_column(String(16), default="internal", server_default="internal", nullable=False, index=True)  # tag only; dedup stays global
    # Hierarchy + scoping (Раздел 4A.8–4A.11): where a rule lives and who it
    # affects. Legacy rows keep client_id/client_project_id NULL and are matched
    # by target_url exactly as before (the matcher treats NULL scope as global).
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=True, index=True)
    client_project_id: Mapped[int | None] = mapped_column(ForeignKey("client_projects.id", ondelete="CASCADE"), nullable=True, index=True)
    level: Mapped[str] = mapped_column(String(16), default="internal", server_default="internal", nullable=False, index=True)  # global|internal|client|project|campaign
    scope: Mapped[str] = mapped_column(String(24), default="anchor", server_default="anchor", nullable=False)  # anchor|exact_url|domain|domain_subdomains|donor_target|project
    reason: Mapped[str] = mapped_column(String(255), default="")
    source: Mapped[str] = mapped_column(String(24), default="manual", server_default="manual", nullable=False)  # manual|import|auto|historical|client_forbidden
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active", nullable=False, index=True)  # active|inactive

    # Uniqueness is per ANCHOR, not per target_url. The same donor must not
    # repeat within one anchor (target_url + anchor_text), but the same donor
    # CAN be reused across different anchors — even ones sharing a target_url.
    __table_args__ = (
        UniqueConstraint("target_url", "anchor_text", "donor_url", name="uq_stoplist_anchor_donor"),
        Index("ix_stoplist_target_anchor_donor", "target_url", "anchor_text", "donor_url"),
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


class EmailAccount(Base):
    """Pool of email/password pairs the team uses to register on donors.

    Distinct from DonorAccount (which records 'username X was used on donor Y').
    EmailAccount is the source pool — one email may be used across many donors.
    """
    __tablename__ = "email_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password: Mapped[str] = mapped_column(String(255), default="")
    label: Mapped[str] = mapped_column(String(128), default="")
    comment: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Which employee this account is issued to. NULL = shared pool, visible
    # to everyone. Set = belongs to that user only.
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Client(Base):
    """External customer we sell placements to. Client projects (kind='client')
    hang off this; internal work has no client."""
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_info: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    comment: Mapped[str] = mapped_column(Text, default="")
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    projects: Mapped[list["ClientProject"]] = relationship(back_populates="client", cascade="all, delete-orphan")


class ClientProject(Base):
    __tablename__ = "client_projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    promoted_domain: Mapped[str] = mapped_column(String(255), default="")
    geo: Mapped[str] = mapped_column(String(64), default="")
    language: Mapped[str] = mapped_column(String(64), default="")
    donor_requirements: Mapped[str] = mapped_column(Text, default="")
    planned_count: Mapped[int] = mapped_column(Integer, default=0)
    period_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    client: Mapped[Client] = relationship(back_populates="projects")
    members: Mapped[list["ClientProjectMember"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class ClientProjectMember(Base):
    """M:N — сотрудники, назначенные на клиентский проект."""
    __tablename__ = "client_project_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_project_id: Mapped[int] = mapped_column(ForeignKey("client_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    project: Mapped[ClientProject] = relationship(back_populates="members")

    __table_args__ = (
        UniqueConstraint("client_project_id", "user_id", name="uq_project_member"),
    )


class LinkCheck(Base):
    """Current verification state + queue slot for one placement's ready-link.

    One row per placement (unique). The background worker claims due rows
    (status pending/due AND next_check_at<=now), locks via locked_at, runs a
    check, then writes a LinkCheckResult and reschedules next_check_at.
    """
    __tablename__ = "link_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    placement_id: Mapped[int] = mapped_column(ForeignKey("placements.id", ondelete="CASCADE"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    level: Mapped[int] = mapped_column(Integer, default=1)
    kind: Mapped[str] = mapped_column(String(16), default="internal", index=True)  # internal|client (for filtering)
    expected_url: Mapped[str] = mapped_column(String(1024), default="")
    expected_anchor: Mapped[str] = mapped_column(String(512), default="")
    expected_link_type: Mapped[str] = mapped_column(String(32), default="")
    final_url: Mapped[str] = mapped_column(String(1024), default="")
    found_anchor: Mapped[str] = mapped_column(String(512), default="")
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_dofollow: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    error_reason: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("ix_link_checks_status_next", "status", "next_check_at"),
    )


class LinkCheckResult(Base):
    """Append-only history — one row per check run (not just the last result)."""
    __tablename__ = "link_check_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    placement_id: Mapped[int] = mapped_column(ForeignKey("placements.id", ondelete="CASCADE"), index=True)
    link_check_id: Mapped[int | None] = mapped_column(ForeignKey("link_checks.id", ondelete="CASCADE"), nullable=True, index=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    level: Mapped[int] = mapped_column(Integer, default=1)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    found_url: Mapped[str] = mapped_column(String(1024), default="")
    found_anchor: Mapped[str] = mapped_column(String(512), default="")
    expected_url: Mapped[str] = mapped_column(String(1024), default="")
    expected_anchor: Mapped[str] = mapped_column(String(512), default="")
    final_url: Mapped[str] = mapped_column(String(1024), default="")
    is_dofollow: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    redirect_chain: Mapped[str] = mapped_column(Text, default="")
    error_reason: Mapped[str] = mapped_column(Text, default="")
    raw: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)


class Notification(Base):
    """In-app notification for a manager / teamlead (link problems, etc.)."""
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(48))
    severity: Mapped[str] = mapped_column(String(16), default="info")  # info|warning|error
    entity_type: Mapped[str] = mapped_column(String(32), default="")
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    dedup_key: Mapped[str] = mapped_column(String(255), default="", index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    __table_args__ = (
        Index("ix_notifications_user_read", "user_id", "is_read"),
    )


class AllocationSetting(Base):
    """Internal/client work split + daily/monthly targets. scope='global'
    (user_id NULL) or scope='employee' (per user; overrides global)."""
    __tablename__ = "allocation_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(16), default="global")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    internal_pct: Mapped[int] = mapped_column(Integer, default=50)
    client_pct: Mapped[int] = mapped_column(Integer, default=50)
    daily_target: Mapped[int] = mapped_column(Integer, default=0)
    monthly_target: Mapped[int] = mapped_column(Integer, default=0)
    period_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


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
