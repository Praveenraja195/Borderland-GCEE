import uuid
from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict


class AceSpadeSubmitRequest(BaseModel):
    moves: int
    wrong_picks: int
    correct_picks: int
    completion_time_seconds: float | None = None


class AceSpadeResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    result_id: uuid.UUID
    round_id: uuid.UUID
    team_id: uuid.UUID
    moves: int
    wrong_picks: int
    correct_picks: int
    completion_time: timedelta | None
    round_score: float
    submitted_at: datetime


class AceSpadeSubroundScore(BaseModel):
    round_number: int
    score: float
    correct_picks: int | None = None
    wrong_picks: int | None = None
    submitted: bool = False


class AceSpadeRoomLeaderboardEntry(BaseModel):
    team_id: uuid.UUID
    team_code: str
    team_name: str
    team_suit_code: str | None = None
    team_suit_symbol: str | None = None
    subrounds: list[AceSpadeSubroundScore]
    total_score: float
    rank: int
    is_current_team: bool = False


# --- Admin surface -----------------------------------------------------


class AceSpadeResultOverride(BaseModel):
    round_score: float
    reason: str
