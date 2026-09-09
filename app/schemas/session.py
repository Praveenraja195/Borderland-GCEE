import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.game import SessionStatus


class SessionStartRequest(BaseModel):
    # Audit Issue 9: unbounded ints let an admin typo (e.g. rounds=0) create
    # a session with no game rounds, which silently zeroes that game's
    # contribution to the leaderboard.
    duration_minutes: int = Field(10, ge=1, le=60)
    rounds: int = Field(5, ge=1, le=10)


class TeamSubmissionDetail(BaseModel):
    team_id: uuid.UUID
    team_code: str
    team_name: str
    submitted_at: datetime | None = None
    submitted_at_str: str | None = None
    score: float | None = None
    detail: str | None = None


class RoundStatusEntry(BaseModel):
    round_number: int
    round_id: uuid.UUID
    deadline: datetime | None
    is_closed: bool | None = None
    submitted: bool = False
    score: float | None = None
    mistakes: int | None = None
    correct_tiles: int | None = None
    correct_picks: int | None = None
    wrong_picks: int | None = None
    start_time: datetime | None = None
    submitted_teams: list[str] = []
    submission_details: list[TeamSubmissionDetail] = []
    viewed_teams: list[str] = []
    is_computed: bool = False


class ViewAckRequest(BaseModel):
    view_type: str = Field(..., description="PUBLISHED_RESULTS, JH_MID_GAME, KD_REVEAL, MM_REVEAL")
    round_id: uuid.UUID | None = None


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: uuid.UUID
    round_id: uuid.UUID
    room_id: uuid.UUID
    room_code: str | None = None
    game_id: uuid.UUID
    game_code: str | None = None
    status: SessionStatus
    start_time: datetime | None
    end_time: datetime | None
    paused_at: datetime | None = None
    instruction_until: datetime | None = None
    is_published: bool = False
    total_room_teams: int = 0
    published_viewed_teams: list[str] = []
    active_team_codes: list[str] = []
    rounds: list[RoundStatusEntry] = []


class SessionWithRoundsOut(BaseModel):
    session: SessionOut
    rounds: list[RoundStatusEntry]


# --- Admin surface (Part 2 §2.5) --------------------------------------------


class SessionDeadlineUpdate(BaseModel):
    new_deadline: datetime


class SessionRoundOut(BaseModel):
    """A session together with the per-room-round deadlines/status a
    ROOM_ADMIN needs to monitor and control it."""

    session: SessionOut
    game_code: str
    rounds: list[RoundStatusEntry]


# --- §1 cross-room/round-wide control ---------------------------------------


class RoomFanOutSuccess(BaseModel):
    room_id: uuid.UUID
    room_code: str
    session_id: uuid.UUID


class RoomFanOutFailure(BaseModel):
    room_id: uuid.UUID
    room_code: str
    reason: str


class SessionFanOutOut(BaseModel):
    """Result of a round-scoped action fanned out across every room in the
    round whose lineup includes game_code — e.g. '9/10 rooms started, Room
    06 failed: already running' instead of a bare 500/409."""

    game_code: str
    round_id: uuid.UUID
    succeeded: list[RoomFanOutSuccess]
    failed: list[RoomFanOutFailure]
