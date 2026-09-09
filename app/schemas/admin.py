import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.admin import AdminRole


class QualificationRuleUpsert(BaseModel):
    top_n: int
    room_id: uuid.UUID | None = None


class QualificationRuleOut(BaseModel):
    rule_id: uuid.UUID
    round_id: uuid.UUID
    room_id: uuid.UUID | None
    top_n: int


# --- Admin account management (Part 2 §2.9) ---------------------------------


class AdminAccountCreate(BaseModel):
    username: str
    password: str
    role: AdminRole


class AdminAccountOut(BaseModel):
    admin_id: uuid.UUID
    username: str
    role: AdminRole
    room_id: uuid.UUID | None = None
    created_at: datetime


class AdminPasswordReset(BaseModel):
    new_password: str


class AdminRoomAssign(BaseModel):
    """§2.9: binds (or unbinds, if room_id is null) a ROOM_ADMIN to a room."""

    room_id: uuid.UUID | None = None


# --- Scheduler & job control (Part 2 §2.8) ----------------------------------


class SchedulerJobOut(BaseModel):
    job_id: str
    game_code: str | None
    round_id: str | None
    run_date: datetime | None


class SchedulerJobCreate(BaseModel):
    game_code: str
    round_id: uuid.UUID
    run_at: datetime
