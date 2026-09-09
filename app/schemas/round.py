import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.round import RoomStatus, RoundStatus


class RoundCreate(BaseModel):
    round_number: int
    name: str
    # Audit §3: previously hardcoded to exactly 10 in the route. Defaults to
    # 10 to match existing behavior, but is now overridable if a future
    # round needs a different room count.
    num_rooms: int = 10


class AutoRoundCreate(BaseModel):
    """Creates a round with rooms auto-calculated from registered team count."""
    name: str = "Round 1"
    teams_per_room: int = 4


class RoundStatusUpdate(BaseModel):
    status: RoundStatus


class RoundOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    round_id: uuid.UUID
    round_number: int
    name: str
    status: RoundStatus
    start_time: datetime | None
    end_time: datetime | None


class RoomOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    room_id: uuid.UUID
    round_id: uuid.UUID
    room_number: int
    room_code: str
    status: RoomStatus


class RoomDetailOut(RoomOut):
    team_count: int
    session_statuses: dict[str, str]


# --- Admin surface (Part 2 §2.3, §2.4) --------------------------------------


class RoundListEntry(BaseModel):
    round_id: uuid.UUID
    round_number: int
    name: str
    status: RoundStatus
    room_count: int


class RoundDetailOut(BaseModel):
    round_id: uuid.UUID
    round_number: int
    name: str
    status: RoundStatus
    rooms: list[RoomDetailOut]


class RoomStatusUpdate(BaseModel):
    status: RoomStatus


class GameLineupEntry(BaseModel):
    game_code: str
    game_order: int


class GameLineupOut(GameLineupEntry):
    game_id: uuid.UUID
    game_name: str
