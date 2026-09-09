import uuid
from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict


class MindmazeSubmitRequest(BaseModel):
    moves: int
    mistakes: int
    correct_tiles: int
    completion_time_seconds: float | None = None


class MindmazeResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    result_id: uuid.UUID
    round_id: uuid.UUID
    team_id: uuid.UUID
    moves: int
    mistakes: int
    correct_tiles: int
    completion_time: timedelta | None
    round_score: float
    submitted_at: datetime


class MindmazeSubroundScore(BaseModel):
    round_number: int
    score: float
    correct_tiles: int | None = None
    mistakes: int | None = None
    submitted: bool = False


class MindmazeRoomLeaderboardEntry(BaseModel):
    team_id: uuid.UUID
    team_code: str
    team_name: str
    team_suit_code: str | None = None
    team_suit_symbol: str | None = None
    subrounds: list[MindmazeSubroundScore]
    total_score: float
    rank: int
    is_current_team: bool = False


# --- Admin surface (Part 2 §2.6) --------------------------------------------


class MindmazeResultOverride(BaseModel):
    round_score: float
    reason: str
