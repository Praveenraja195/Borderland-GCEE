import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.core.exceptions import ConflictError, NotFoundError
from app.db.session import get_db
from app.models.admin import AdminRole
from app.models.game import Game, GameSession, RoundGames
from app.models.round import Room, RoomStatus, Round, RoundStatus
from app.models.selection import Round1Selection, Suit
from app.schemas.round import (
    AutoRoundCreate,
    GameLineupEntry,
    GameLineupOut,
    RoomDetailOut,
    RoomOut,
    RoomStatusUpdate,
    RoundCreate,
    RoundDetailOut,
    RoundListEntry,
    RoundOut,
    RoundStatusUpdate,
)
from app.models.team import Team
from app.schemas.selection import RoomMoveRequest, SelectionOut
from app.services import admin_service

router = APIRouter(tags=["rounds"])

_ROUND_STATUS_ORDER = [RoundStatus.NOT_STARTED, RoundStatus.ACTIVE, RoundStatus.COMPLETED]
# Fix §3.1: room status now has the same one-step state-machine enforcement
# as round status. A COMPLETED room cannot be rolled back to ACTIVE by mistake.
_ROOM_STATUS_ORDER = [RoomStatus.NOT_STARTED, RoomStatus.ACTIVE, RoomStatus.COMPLETED]


async def _room_detail(db: AsyncSession, room: Room) -> RoomDetailOut:
    team_count = (
        await db.execute(select(func.count()).select_from(Round1Selection).where(Round1Selection.room_id == room.room_id))
    ).scalar_one()
    sessions = (await db.execute(select(GameSession).where(GameSession.room_id == room.room_id))).scalars().all()
    session_statuses = {str(s.game_id): s.status.value for s in sessions}
    return RoomDetailOut(
        room_id=room.room_id,
        round_id=room.round_id,
        room_number=room.room_number,
        room_code=room.room_code,
        status=room.status,
        team_count=team_count,
        session_statuses=session_statuses,
    )


# ---------------------------------------------------------------------------
# §2.3 Round & Room Configuration
# ---------------------------------------------------------------------------


@router.get("/rounds/active", response_model=RoundOut)
async def get_active_round(db: AsyncSession = Depends(get_db)):
    """Returns the current active or latest round for team applications."""
    from datetime import datetime, timedelta, timezone

    stmt = (
        select(Round)
        .where(Round.status.in_([RoundStatus.ACTIVE, RoundStatus.NOT_STARTED]))
        .order_by(Round.status == RoundStatus.ACTIVE, Round.round_number.desc())
        .limit(1)
    )
    round_obj = (await db.execute(stmt)).scalar_one_or_none()
    if round_obj is None:
        stmt_completed = select(Round).order_by(Round.round_number.desc()).limit(1)
        round_obj = (await db.execute(stmt_completed)).scalar_one_or_none()
    if round_obj is None:
        raise NotFoundError("No round configured yet")

    if round_obj.status == RoundStatus.ACTIVE and round_obj.start_time and not round_obj.end_time:
        round_obj.end_time = round_obj.start_time + timedelta(minutes=55)
        await db.commit()
        await db.refresh(round_obj)

    return round_obj


@router.post("/admin/rounds", response_model=RoundOut, status_code=status.HTTP_201_CREATED)
async def create_round(
    payload: RoundCreate,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    round_obj = Round(round_number=payload.round_number, name=payload.name)
    db.add(round_obj)
    await db.flush()

    for n in range(1, payload.num_rooms + 1):
        db.add(Room(round_id=round_obj.round_id, room_number=n, room_code=f"R{n:02d}"))

    await db.commit()
    await db.refresh(round_obj)
    return round_obj


@router.post("/admin/rounds/auto", response_model=RoundDetailOut, status_code=status.HTTP_201_CREATED)
async def auto_create_round(
    payload: AutoRoundCreate,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    """Auto-creates a round with rooms calculated from registered team count.
    Default: 4 teams per room (one per suit). Leftover teams can be manually
    assigned to any room by the admin afterwards."""
    import math

    # Check no round exists yet
    existing = (await db.execute(select(Round).limit(1))).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("A round already exists. Delete the existing round first or use the standard create endpoint.")

    team_count = (await db.execute(select(func.count()).select_from(Team))).scalar_one()
    if team_count == 0:
        raise ConflictError("No teams registered yet. Create teams first, then create rooms.")

    num_rooms = math.ceil(team_count / payload.teams_per_room)
    if num_rooms < 1:
        num_rooms = 1

    round_obj = Round(round_number=1, name=payload.name)
    db.add(round_obj)
    await db.flush()

    for n in range(1, num_rooms + 1):
        db.add(Room(round_id=round_obj.round_id, room_number=n, room_code=f"R{n:02d}"))

    # Auto-set game lineup with all 3 games
    games = (await db.execute(select(Game))).scalars().all()
    for i, game in enumerate(games, start=1):
        db.add(RoundGames(round_id=round_obj.round_id, game_id=game.game_id, game_order=i))

    await db.commit()
    await db.refresh(round_obj)

    # Return full detail with rooms
    rooms = (
        (await db.execute(select(Room).where(Room.round_id == round_obj.round_id).order_by(Room.room_number)))
        .scalars()
        .all()
    )
    room_details = [await _room_detail(db, room) for room in rooms]
    return RoundDetailOut(
        round_id=round_obj.round_id,
        round_number=round_obj.round_number,
        name=round_obj.name,
        status=round_obj.status,
        rooms=room_details,
    )


@router.delete("/admin/rounds/{round_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_round(
    round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    """Deletes a round, resetting the event state so a new round can be created from scratch."""
    round_obj = await db.get(Round, round_id)
    if round_obj is None:
        raise NotFoundError("Round not found")
    await db.delete(round_obj)
    await db.commit()


@router.get("/admin/rounds", response_model=list[RoundListEntry])
async def list_rounds(
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    rounds = (await db.execute(select(Round).order_by(Round.round_number))).scalars().all()
    out = []
    for r in rounds:
        room_count = (
            await db.execute(select(func.count()).select_from(Room).where(Room.round_id == r.round_id))
        ).scalar_one()
        out.append(
            RoundListEntry(
                round_id=r.round_id, round_number=r.round_number, name=r.name, status=r.status, room_count=room_count
            )
        )
    return out


@router.get("/admin/rounds/{round_id}", response_model=RoundDetailOut)
async def get_round_detail(
    round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    round_obj = await db.get(Round, round_id)
    if round_obj is None:
        raise NotFoundError("Round not found")

    # Auto-seed game lineup if empty or if new games have been registered
    from app.models.game import RoundGames
    existing_game_ids = set(
        (await db.execute(select(RoundGames.game_id).where(RoundGames.round_id == round_id))).scalars().all()
    )
    games = (await db.execute(select(Game))).scalars().all()
    max_order = (
        await db.execute(
            select(func.coalesce(func.max(RoundGames.game_order), 0)).where(RoundGames.round_id == round_id)
        )
    ).scalar() or 0
    added = False
    for game in games:
        if game.game_id not in existing_game_ids:
            max_order += 1
            db.add(RoundGames(round_id=round_id, game_id=game.game_id, game_order=max_order))
            added = True
    if added:
        await db.commit()

    rooms = (
        (await db.execute(select(Room).where(Room.round_id == round_id).order_by(Room.room_number)))
        .scalars()
        .all()
    )
    room_details = [await _room_detail(db, room) for room in rooms]
    return RoundDetailOut(
        round_id=round_obj.round_id,
        round_number=round_obj.round_number,
        name=round_obj.name,
        status=round_obj.status,
        rooms=room_details,
    )


@router.patch("/admin/rounds/{round_id}/status", response_model=RoundOut)
async def update_round_status(
    round_id: uuid.UUID,
    payload: RoundStatusUpdate,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    from datetime import datetime, timedelta, timezone

    round_obj = await db.get(Round, round_id)
    if round_obj is None:
        raise NotFoundError("Round not found")

    current_idx = _ROUND_STATUS_ORDER.index(round_obj.status)
    target_idx = _ROUND_STATUS_ORDER.index(payload.status)
    if target_idx != current_idx + 1:
        raise ConflictError(
            f"Cannot transition round from {round_obj.status.value} to {payload.status.value}; "
            "status must advance one step at a time (NOT_STARTED → ACTIVE → COMPLETED)."
        )

    round_obj.status = payload.status
    if payload.status == RoundStatus.ACTIVE:
        now = datetime.now(timezone.utc)
        if round_obj.start_time is None:
            round_obj.start_time = now
        if round_obj.end_time is None:
            round_obj.end_time = round_obj.start_time + timedelta(minutes=55)
    elif payload.status == RoundStatus.COMPLETED:
        if round_obj.end_time is None:
            round_obj.end_time = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(round_obj)
    return round_obj


@router.get("/admin/rooms", response_model=list[RoomOut])
async def list_rooms(
    round_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    stmt = select(Room).order_by(Room.round_id, Room.room_number)
    if round_id is not None:
        stmt = stmt.where(Room.round_id == round_id)
    rooms = (await db.execute(stmt)).scalars().all()
    return rooms


@router.get("/admin/rooms/{room_id}", response_model=RoomDetailOut)
async def get_room_detail(
    room_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    room = await db.get(Room, room_id)
    if room is None:
        raise NotFoundError("Room not found")
    return await _room_detail(db, room)


@router.patch("/admin/rooms/{room_id}/status", response_model=RoomOut)
async def update_room_status(
    room_id: uuid.UUID,
    payload: RoomStatusUpdate,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    """Fix §3.1: room status now enforces the same one-step state-machine as
    round status. Prevents a COMPLETED room being rolled back to ACTIVE after
    fn_compute_room_results has already published rankings."""
    room = await db.get(Room, room_id)
    if room is None:
        raise NotFoundError("Room not found")

    try:
        current_idx = _ROOM_STATUS_ORDER.index(room.status)
        target_idx = _ROOM_STATUS_ORDER.index(payload.status)
    except ValueError:
        raise ConflictError(f"Invalid room status value: {payload.status}")

    if target_idx != current_idx + 1:
        raise ConflictError(
            f"Cannot transition room from {room.status.value} to {payload.status.value}; "
            "room status must advance one step at a time (NOT_STARTED → ACTIVE → COMPLETED)."
        )

    room.status = payload.status
    await db.commit()
    await db.refresh(room)
    return room


# ---------------------------------------------------------------------------
# §2.2 Room Assignment Override (Move a Team)
# ---------------------------------------------------------------------------


@router.patch("/admin/rounds/{round_id}/teams/{team_id}/room", response_model=SelectionOut)
async def move_team_room(
    round_id: uuid.UUID,
    team_id: uuid.UUID,
    payload: RoomMoveRequest,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    return await admin_service.move_team_room(
        db, round_id=round_id, team_id=team_id, target_number=payload.target_number
    )


@router.delete("/admin/rounds/{round_id}/teams/{team_id}/selection", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team_selection(
    round_id: uuid.UUID,
    team_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    await admin_service.delete_team_selection(db, round_id=round_id, team_id=team_id)


@router.get("/admin/rounds/{round_id}/rooms/{room_id}/availability", response_model=list[dict])
async def room_suit_availability(
    round_id: uuid.UUID,
    room_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    """Fix §3.2: verify room belongs to this round before computing availability.
    Previously the room was fetched by room_id alone and the taken query used
    round_id separately — mismatched IDs returned plausible-looking bad data."""
    room = await db.get(Room, room_id)
    if room is None:
        raise NotFoundError("Room not found")

    # Fix §3.2: cross-round check.
    if room.round_id != round_id:
        raise ConflictError(
            f"Room {room_id} does not belong to round {round_id}. "
            "Check your round_id parameter."
        )

    suits = (await db.execute(select(Suit))).scalars().all()
    taken = set(
        (
            await db.execute(
                select(Round1Selection.suit_id).where(
                    Round1Selection.round_id == round_id,
                    Round1Selection.room_id == room_id,
                )
            )
        )
        .scalars()
        .all()
    )
    return [{"suit_code": s.code, "is_taken": s.suit_id in taken} for s in suits]


# ---------------------------------------------------------------------------
# §2.4 Game Lineup per Round
# ---------------------------------------------------------------------------


@router.get("/admin/rounds/{round_id}/games", response_model=list[GameLineupOut])
async def get_round_game_lineup(
    round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    rows = (
        await db.execute(
            select(RoundGames.game_order, Game.game_id, Game.code, Game.name)
            .join(Game, Game.game_id == RoundGames.game_id)
            .where(RoundGames.round_id == round_id)
            .order_by(RoundGames.game_order)
        )
    ).all()
    return [
        GameLineupOut(game_code=row.code, game_order=row.game_order, game_id=row.game_id, game_name=row.name)
        for row in rows
    ]


@router.put("/admin/rounds/{round_id}/games", response_model=list[GameLineupOut])
async def replace_round_game_lineup(
    round_id: uuid.UUID,
    payload: list[GameLineupEntry],
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    return await admin_service.replace_game_lineup(db, round_id=round_id, entries=payload)


@router.delete("/admin/rounds/{round_id}/games/{game_code}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_round_game(
    round_id: uuid.UUID,
    game_code: str,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    await admin_service.remove_round_game(db, round_id=round_id, game_code=game_code.upper())
