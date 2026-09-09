import uuid

from pydantic import BaseModel


class RoomLeaderboardEntry(BaseModel):
    room_id: uuid.UUID
    room_code: str
    team_code: str
    team_name: str
    team_suit_code: str | None = None
    team_suit_symbol: str | None = None
    mindmaze_score: float | None = None
    ace_spade_score: float | None = None
    king_diamond_score: float | None = None
    jack_heart_score: float | None = None
    total_score: float | None = None
    live_rank: int | None = None
    is_qualified: bool | None = None
    is_published: bool = False


class OverallLeaderboardEntry(BaseModel):
    team_code: str
    team_name: str
    room_code: str
    team_suit_code: str | None = None
    team_suit_symbol: str | None = None
    mindmaze_score: float | None = None
    ace_spade_score: float | None = None
    king_diamond_score: float | None = None
    jack_heart_score: float | None = None
    total_score: float | None = None
    is_qualified: bool | None = None
    overall_rank: int | None = None
    is_published: bool = False


class GameLeaderboardEntry(BaseModel):
    game_code: str
    game_name: str
    room_code: str
    team_code: str
    team_name: str
    team_suit_code: str | None = None
    team_suit_symbol: str | None = None
    score: float
    game_rank: int
