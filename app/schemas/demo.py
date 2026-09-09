"""Request/response models for the demo (practice) round surface.

Deliberately loose on the response side — the demo endpoints return plain
dicts assembled by `app/services/demo_service.py` from Redis, and pinning
them to strict models here would mean maintaining a second copy of every
game's payload shape for no gain. What IS pinned is every *request* body,
so a practice submission can't smuggle in an unbounded value.
"""

import uuid

from pydantic import BaseModel, Field


class DemoStartRequest(BaseModel):
    # Same bounds as SessionStartRequest, minus the room for manoeuvre: a
    # practice run is meant to be short.
    duration_minutes: int = Field(1, ge=1, le=60)
    rounds: int = Field(1, ge=1, le=5)


class DemoRestartRequest(BaseModel):
    """Every field optional — an empty body means "same shape, deal again",
    which is the common case when a room wants another practice go."""

    duration_minutes: int | None = Field(None, ge=1, le=60)
    rounds: int | None = Field(None, ge=1, le=5)


class DemoMindmazeSubmitRequest(BaseModel):
    moves: int = Field(0, ge=0)
    mistakes: int = Field(0, ge=0)
    correct_tiles: int = Field(0, ge=0)
    completion_time_seconds: float | None = Field(None, ge=0)


class DemoAceSpadeSubmitRequest(BaseModel):
    moves: int = Field(0, ge=0)
    wrong_picks: int = Field(0, ge=0)
    correct_picks: int = Field(0, ge=0)
    completion_time_seconds: float | None = Field(None, ge=0)


class DemoKingDiamondSubmitRequest(BaseModel):
    submitted_number: float = Field(..., ge=0, le=100)


class DemoJackHeartSubmitRequest(BaseModel):
    submitted_symbol_id: int = Field(..., ge=1)


class DemoRoomOutcome(BaseModel):
    room_id: uuid.UUID
    room_code: str
    ok: bool
    reason: str | None = None


class DemoFanOutOut(BaseModel):
    """Per-room result of a round-wide demo action, mirroring
    SessionFanOutOut so the admin UI reports partial failures the same way
    it already does for real sessions."""

    game_code: str
    round_id: uuid.UUID
    succeeded: list[DemoRoomOutcome] = []
    failed: list[DemoRoomOutcome] = []
