import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TeamCreate(BaseModel):
    team_code: str
    team_name: str
    password: str


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    team_id: uuid.UUID
    team_code: str
    team_name: str
    leader_name: str | None = None
    leader_phone: str | None = None
    leader_email: str | None = None
    created_at: datetime


# --- Admin surface (Part 2 §2.1) -------------------------------------------


class TeamAdminListEntry(BaseModel):
    team_id: uuid.UUID
    team_code: str
    team_name: str
    created_at: datetime
    room_code: str | None = None
    suit_code: str | None = None
    has_selected: bool
    # Populated for teams created through the spreadsheet import (migration
    # 0010); NULL for teams created through the single-team admin form.
    leader_name: str | None = None
    leader_phone: str | None = None
    leader_email: str | None = None


class TeamAdminDetailOut(BaseModel):
    team_id: uuid.UUID
    team_code: str
    team_name: str
    created_at: datetime
    room_code: str | None = None
    suit_code: str | None = None
    selected_number: int | None = None
    has_selected: bool
    game_scores: list[dict]
    leader_name: str | None = None
    leader_phone: str | None = None
    leader_email: str | None = None


class TeamPasswordReset(BaseModel):
    new_password: str


# --- Bulk registration import (app/services/team_import_service.py) --------


class ImportRowOut(BaseModel):
    """One row of the uploaded sheet, as the preview reports it.

    `team_code` and `password` are the real values the commit will use, not
    samples — the admin reviews exactly what the teams will log in with.
    Rows whose `status` is not "OK" carry an empty `team_code`.
    """

    row_number: int
    team_name: str
    leader_name: str
    leader_phone: str
    leader_email: str
    team_code: str
    password: str
    status: str
    message: str


class ImportPreviewOut(BaseModel):
    headers: list[str]
    column_map: dict[str, int]
    unmapped_required: list[str]
    header_row_number: int
    sheet_name: str | None = None
    existing_team_count: int
    capacity_remaining: int
    rows: list[ImportRowOut]
    importable_count: int
    skipped_count: int


class ImportRowIn(BaseModel):
    """A row the admin confirmed in the preview, sent back to be created."""

    team_name: str
    leader_name: str = ""
    leader_phone: str = ""
    leader_email: str = ""
    team_code: str = ""
    password: str = ""


class ImportCommitIn(BaseModel):
    rows: list[ImportRowIn]


class ImportedTeamOut(BaseModel):
    team_id: uuid.UUID
    team_code: str
    team_name: str
    password: str
    leader_name: str | None = None
    leader_phone: str | None = None
    leader_email: str | None = None


class ImportCommitOut(BaseModel):
    created_count: int
    teams: list[ImportedTeamOut]
