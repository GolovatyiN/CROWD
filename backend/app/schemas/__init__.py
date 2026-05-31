from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict

# Plain str instead of EmailStr — pydantic's email-validator rejects reserved
# TLDs like .local / .test which we use for the seeded demo accounts.
EmailStr = str


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Auth / Users ----------

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserBase(BaseModel):
    email: EmailStr
    full_name: str = ""
    role: str = "employee"


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


class UserOut(ORMModel):
    id: int
    email: EmailStr
    full_name: str
    role: str
    is_active: bool
    created_at: datetime


# ---------- Donors ----------

class DonorBase(BaseModel):
    donor_url: str
    tr: float = 0
    organic_traffic: int = 0
    ref_domains: int = 0
    backlinks: int = 0
    geo: str = ""
    language: str = ""
    link_type: str = "unknown"
    category: str = ""
    status: str = "active"
    comment: str = ""
    is_active: bool = True


class DonorCreate(DonorBase):
    pass


class DonorUpdate(BaseModel):
    donor_url: Optional[str] = None
    tr: Optional[float] = None
    organic_traffic: Optional[int] = None
    ref_domains: Optional[int] = None
    backlinks: Optional[int] = None
    geo: Optional[str] = None
    language: Optional[str] = None
    link_type: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = None
    comment: Optional[str] = None
    is_active: Optional[bool] = None


class DonorOut(ORMModel):
    id: int
    donor_url: str
    domain: str
    tr: float
    organic_traffic: int
    ref_domains: int
    backlinks: int
    geo: str
    language: str
    link_type: str
    category: str
    status: str
    comment: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ---------- Donor accounts ----------

class DonorAccountBase(BaseModel):
    login_email: str = ""
    login_password: str = ""
    account_username: str = ""
    comment: str = ""
    is_active: bool = True
    max_placements: int = 0


class DonorAccountCreate(DonorAccountBase):
    donor_id: int


class DonorAccountUpdate(BaseModel):
    login_email: Optional[str] = None
    login_password: Optional[str] = None
    account_username: Optional[str] = None
    comment: Optional[str] = None
    is_active: Optional[bool] = None
    max_placements: Optional[int] = None


class DonorAccountOut(ORMModel):
    id: int
    donor_id: int
    login_email: str
    login_password: str
    account_username: str
    comment: str
    is_active: bool
    max_placements: int
    usage_count: int = 0
    created_at: datetime


# ---------- Email accounts (shared pool) ----------

class EmailAccountBase(BaseModel):
    email: str
    password: str = ""
    label: str = ""
    comment: str = ""
    is_active: bool = True


class EmailAccountCreate(EmailAccountBase):
    pass


class EmailAccountUpdate(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None
    label: Optional[str] = None
    comment: Optional[str] = None
    is_active: Optional[bool] = None


class EmailAccountOut(ORMModel):
    id: int
    email: str
    password: str
    label: str
    comment: str
    is_active: bool
    created_by: Optional[int]
    created_at: datetime
    usage_count: int = 0


# ---------- Anchor plans ----------

class AnchorPlanOut(ORMModel):
    id: int
    plan_name: str
    uploaded_file_name: str
    status: str
    created_by: Optional[int]
    created_at: datetime
    total_rows: int = 0
    completed_rows: int = 0
    pending_rows: int = 0
    problem_rows: int = 0


class AnchorPlanItemOut(ORMModel):
    id: int
    anchor_plan_id: int
    target_domain: str
    target_url: str
    anchor_text: str
    geo: str
    language: str
    required_link_type: str
    requirements: str
    assigned_to: Optional[int]
    selected_donor_id: Optional[int]
    status: str
    result_url: str
    comment: str
    created_at: datetime
    updated_at: datetime


class AnchorPlanItemUpdate(BaseModel):
    anchor_text: Optional[str] = None
    target_url: Optional[str] = None
    geo: Optional[str] = None
    language: Optional[str] = None
    required_link_type: Optional[str] = None
    requirements: Optional[str] = None
    assigned_to: Optional[int] = None
    selected_donor_id: Optional[int] = None
    status: Optional[str] = None
    comment: Optional[str] = None


class AssignRequest(BaseModel):
    item_ids: List[int]
    assigned_to: int


class AutoMatchResult(BaseModel):
    matched: int
    not_matched: int
    items_problem: List[int] = []
    considered: int = 0


# ---------- Placements ----------

class PlacementOut(ORMModel):
    id: int
    anchor_plan_item_id: Optional[int]
    target_domain: str
    target_url: str
    donor_id: Optional[int]
    donor_url: str
    anchor_text: str
    employee_id: Optional[int]
    donor_account_id: Optional[int]
    result_url: str
    status: str
    login_email: str
    login_password: str
    account_username: str
    comment: str
    created_at: datetime
    placed_at: Optional[datetime]


class MarkPlacedRequest(BaseModel):
    result_url: str
    login_email: str = ""
    login_password: str = ""
    account_username: str = ""
    comment: str = ""


class MarkProblemRequest(BaseModel):
    comment: str = ""


# ---------- Stop list ----------

class StopListOut(ORMModel):
    id: int
    target_domain: str
    target_url: str
    donor_id: Optional[int]
    donor_url: str
    anchor_plan_item_id: Optional[int]
    placed_by: Optional[int]
    placed_at: datetime
    result_url: str
    anchor_text: str
    account_username: str
    login_email: str
    source_anchor_plan: str
    comment: str


# ---------- Import ----------

class ImportPreview(BaseModel):
    rows_total: int
    rows_inserted: int
    rows_updated: int
    rows_skipped: int
    rows_failed: int
    errors: List[dict] = []
    log_id: Optional[int] = None
    plan_id: Optional[int] = None


# Resolve forward refs
TokenResponse.model_rebuild()
