import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class JackHeartSubmitRequest(BaseModel):
    submitted_symbol_id: int


class JackHeartAnswerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    answer_id: uuid.UUID
    round_id: uuid.UUID
    team_id: uuid.UUID
    submitted_symbol_id: int
    is_correct: bool
    round_score: float
    submitted_at: datetime


class JHSymbolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    symbol_id: int
    code: str
    label: str
    suit: str | None = None
    rank: str | None = None


class VisibleSymbolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    team_id: uuid.UUID
    team_code: str
    team_name: str
    team_suit_code: str | None = None
    team_suit_symbol: str | None = None
    symbol_id: int
    symbol_code: str
    symbol_label: str
    suit: str | None = None
    rank: str | None = None


# --- Admin surface (Part 2 §2.6) --------------------------------------------


class JackHeartAssignmentAdminOut(BaseModel):
    """Full symbol assignment table for a round — SUPER_ADMIN only, since a
    compromised ROOM_ADMIN account seeing this would leak every team's
    hidden symbol."""

    team_id: uuid.UUID
    team_code: str
    team_name: str
    team_suit_code: str | None = None
    team_suit_symbol: str | None = None
    symbol_id: int
    symbol_code: str
    symbol_label: str
    suit: str | None = None
    rank: str | None = None
