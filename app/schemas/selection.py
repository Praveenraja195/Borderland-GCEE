import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SelectionCreate(BaseModel):
    suit_code: str = Field(..., description="HEART, SPADE, CLUB, or DIAMOND")
    selected_number: int = Field(..., ge=1, le=10)


class SelectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    selection_id: uuid.UUID
    round_id: uuid.UUID
    team_id: uuid.UUID
    suit_id: int
    suit_code: str | None = None
    selected_number: int
    room_id: uuid.UUID | None
    is_locked: bool
    selected_at: datetime


# --- Availability (Audit Issue 5) -------------------------------------------


class NumberAvailability(BaseModel):
    number: int
    is_taken: bool


class SelectionAvailabilityOut(BaseModel):
    suit_code: str
    numbers: list[NumberAvailability]


# --- Admin room-assignment override (Part 2 §2.2) ---------------------------


class RoomMoveRequest(BaseModel):
    target_number: int = Field(..., ge=1, le=10)
