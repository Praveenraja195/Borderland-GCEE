import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class KingDiamondSubmitRequest(BaseModel):
    submitted_number: float = Field(..., ge=0, le=100)


class KingDiamondSubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    submission_id: uuid.UUID
    round_id: uuid.UUID
    team_id: uuid.UUID
    submitted_number: float
    submitted_at: datetime
    is_valid: bool
    difference: float | None
    rank: int | None
    round_score: float
    is_winner: bool


class TeamSubmissionReveal(BaseModel):
    """One team's submission in the all-teams reveal after round closes."""
    team_code: str
    team_id: str
    submitted_number: float
    is_valid: bool
    difference: float | None = None
    rank: int | None = None
    penalty: float = 0.0
    round_score: float = 0.0
    is_you: bool = False


class KingDiamondRoundResultOut(BaseModel):
    """Team-facing computation reveal for one sub-round.
    After closure: includes all_submissions so the frontend can show
    every team's number, the average calculation, and scoring breakdown."""

    round_id: uuid.UUID
    round_number: int
    is_closed: bool
    average_value: float | None = None
    target_value: float | None = None
    submitted_number: float | None = None
    difference: float | None = None
    rank: int | None = None
    round_score: float = 0.0
    penalty: float = 0.0
    base_points: int
    is_valid: bool = False
    total_teams: int = 0
    all_submissions: list[TeamSubmissionReveal] = []


# --- Admin surface (Part 2 §2.6) --------------------------------------------


class KingDiamondSubmissionOverride(BaseModel):
    is_valid: bool | None = None
    round_score: float | None = None
    reason: str


class KingDiamondSubroundScore(BaseModel):
    round_number: int
    score: float
    submitted_number: float | None = None
    rank: int | None = None
    difference: float | None = None
    submitted: bool = False


class KingDiamondRoomLeaderboardEntry(BaseModel):
    team_id: uuid.UUID
    team_code: str
    team_name: str
    team_suit_code: str | None = None
    team_suit_symbol: str | None = None
    subrounds: list[KingDiamondSubroundScore]
    total_score: float
    rank: int
    is_current_team: bool = False

