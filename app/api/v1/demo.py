"""
Demo (practice) rounds — routes.

Two surfaces, both thin wrappers over `app/services/demo_service.py`:

* **Admin** (`/admin/rounds/{round_id}/demo/{game_code}/...`) — the same
  start / pause / resume / restart / sub-round vocabulary as the real
  round-wide session control in `sessions.py`, fanned out across every room
  in the round whose lineup includes that game. `restart` is the one the
  practice loop leans on: it re-deals a fresh attempt from any state, so a
  room can rehearse as many times as it wants.

* **Team** (`/rooms/{room_id}/demo-sessions`, `/demo/...`) — the practice
  twins of the three games' play endpoints, shaped identically to the real
  ones so the team app drives them through the same screens.

Nothing on either surface writes to Postgres; see the module docstring in
`demo_service` for the invariant and how it is kept.
"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_team, require_role
from app.db.session import get_db
from app.models.admin import AdminRole
from app.models.team import Team
from app.schemas.demo import (
    DemoAceSpadeSubmitRequest,
    DemoFanOutOut,
    DemoJackHeartSubmitRequest,
    DemoKingDiamondSubmitRequest,
    DemoMindmazeSubmitRequest,
    DemoRestartRequest,
    DemoRoomOutcome,
    DemoStartRequest,
)
from app.services import demo_service

router = APIRouter(tags=["demo"])


def _fan_out_response(game_code: str, round_id: uuid.UUID, results: list[dict]) -> DemoFanOutOut:
    return DemoFanOutOut(
        game_code=game_code,
        round_id=round_id,
        succeeded=[DemoRoomOutcome(**r) for r in results if r["ok"]],
        failed=[DemoRoomOutcome(**r) for r in results if not r["ok"]],
    )


# ---------------------------------------------------------------------------
# Admin control
#
# Start / restart / end are SUPER_ADMIN, matching the real round-wide
# equivalents (a ROOM_ADMIN bound to one room has no business arming a
# practice round everywhere). Pause/resume and the per-sub-round controls sit
# at ROOM_ADMIN, same as their real counterparts, because those are the
# in-the-moment "hold on, let them try again" actions.
# ---------------------------------------------------------------------------


@router.post(
    "/admin/rounds/{round_id}/demo/{game_code}/start",
    response_model=DemoFanOutOut,
    status_code=status.HTTP_207_MULTI_STATUS,
)
async def start_demo(
    round_id: uuid.UUID,
    game_code: str,
    payload: DemoStartRequest,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    game_code = game_code.upper()
    results = await demo_service.start_demo(
        db,
        round_id=round_id,
        game_code=game_code,
        duration_minutes=payload.duration_minutes,
        num_rounds=payload.rounds,
    )
    return _fan_out_response(game_code, round_id, results)


@router.post(
    "/admin/rounds/{round_id}/demo/{game_code}/restart",
    response_model=DemoFanOutOut,
    status_code=status.HTTP_207_MULTI_STATUS,
)
async def restart_demo(
    round_id: uuid.UUID,
    game_code: str,
    payload: DemoRestartRequest | None = None,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    """"Run it again." Discards the previous attempt entirely and deals a
    fresh one. Works from any state, including a finished demo — this is the
    practice-again control."""
    game_code = game_code.upper()
    payload = payload or DemoRestartRequest()
    results = await demo_service.restart_demo(
        db,
        round_id=round_id,
        game_code=game_code,
        duration_minutes=payload.duration_minutes,
        num_rounds=payload.rounds,
    )
    return _fan_out_response(game_code, round_id, results)


@router.post(
    "/admin/rounds/{round_id}/demo/{game_code}/end",
    response_model=DemoFanOutOut,
    status_code=status.HTTP_207_MULTI_STATUS,
)
async def end_demo(
    round_id: uuid.UUID,
    game_code: str,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    """Tears the practice surface down; team screens fall back to the real
    session immediately."""
    game_code = game_code.upper()
    results = await demo_service.end_demo(db, round_id=round_id, game_code=game_code)
    return _fan_out_response(game_code, round_id, results)


@router.post(
    "/admin/rounds/{round_id}/demo/{game_code}/pause",
    response_model=DemoFanOutOut,
    status_code=status.HTTP_207_MULTI_STATUS,
)
async def pause_demo(
    round_id: uuid.UUID,
    game_code: str,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    game_code = game_code.upper()
    results = await demo_service.pause_demo(db, round_id=round_id, game_code=game_code)
    return _fan_out_response(game_code, round_id, results)


@router.post(
    "/admin/rounds/{round_id}/demo/{game_code}/resume",
    response_model=DemoFanOutOut,
    status_code=status.HTTP_207_MULTI_STATUS,
)
async def resume_demo(
    round_id: uuid.UUID,
    game_code: str,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    game_code = game_code.upper()
    results = await demo_service.resume_demo(db, round_id=round_id, game_code=game_code)
    return _fan_out_response(game_code, round_id, results)


@router.post(
    "/admin/rounds/{round_id}/demo/{game_code}/subrounds/{subround_number}/start",
    response_model=DemoFanOutOut,
    status_code=status.HTTP_207_MULTI_STATUS,
)
async def start_demo_subround(
    round_id: uuid.UUID,
    game_code: str,
    subround_number: int,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    game_code = game_code.upper()
    results = await demo_service.start_demo_subround(
        db, round_id=round_id, game_code=game_code, subround_number=subround_number
    )
    return _fan_out_response(game_code, round_id, results)


@router.post(
    "/admin/rounds/{round_id}/demo/{game_code}/subrounds/{subround_number}/restart",
    response_model=DemoFanOutOut,
    status_code=status.HTTP_207_MULTI_STATUS,
)
async def restart_demo_subround(
    round_id: uuid.UUID,
    game_code: str,
    subround_number: int,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    game_code = game_code.upper()
    results = await demo_service.restart_demo_subround(
        db, round_id=round_id, game_code=game_code, subround_number=subround_number
    )
    return _fan_out_response(game_code, round_id, results)


@router.get("/admin/rounds/{round_id}/demo", response_model=list)
async def list_demo_overview(
    round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    """Live demo state for all three games across every room in the round —
    what the admin dashboard polls."""
    return await demo_service.list_demo_overview(db, round_id=round_id)


@router.get("/admin/rounds/{round_id}/demo/{game_code}", response_model=list)
async def list_demo_for_game(
    round_id: uuid.UUID,
    game_code: str,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    return await demo_service.list_demo_for_round(db, round_id=round_id, game_code=game_code.upper())


# ---------------------------------------------------------------------------
# Team surface
# ---------------------------------------------------------------------------


@router.get("/rooms/{room_id}/demo-sessions", response_model=list)
async def list_demo_sessions(
    room_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_team: Team = Depends(get_current_team),
):
    """Active practice rounds for the caller's room, shaped like the entries
    from `GET /rooms/{room_id}/sessions` (plus `is_demo: true`) so the team
    app can render one through the same game screens."""
    return await demo_service.list_team_demo_sessions(
        db, room_id=room_id, team_id=current_team.team_id
    )


@router.post("/demo/mindmaze/rounds/{demo_round_id}/submit", status_code=status.HTTP_201_CREATED)
async def submit_demo_mindmaze(
    demo_round_id: uuid.UUID,
    payload: DemoMindmazeSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_team: Team = Depends(get_current_team),
):
    return await demo_service.submit_mindmaze(
        db,
        demo_round_id=demo_round_id,
        team_id=current_team.team_id,
        moves=payload.moves,
        mistakes=payload.mistakes,
        correct_tiles=payload.correct_tiles,
        completion_time_seconds=payload.completion_time_seconds,
    )


@router.post("/demo/ace-spade/rounds/{demo_round_id}/submit", status_code=status.HTTP_201_CREATED)
async def submit_demo_ace_spade(
    demo_round_id: uuid.UUID,
    payload: DemoAceSpadeSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_team: Team = Depends(get_current_team),
):
    return await demo_service.submit_ace_spade(
        db,
        demo_round_id=demo_round_id,
        team_id=current_team.team_id,
        moves=payload.moves,
        wrong_picks=payload.wrong_picks,
        correct_picks=payload.correct_picks,
        completion_time_seconds=payload.completion_time_seconds,
    )


@router.post("/demo/king-diamond/rounds/{demo_round_id}/submit", status_code=status.HTTP_201_CREATED)
async def submit_demo_king_diamond(
    demo_round_id: uuid.UUID,
    payload: DemoKingDiamondSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_team: Team = Depends(get_current_team),
):
    return await demo_service.submit_king_diamond(
        db,
        demo_round_id=demo_round_id,
        team_id=current_team.team_id,
        submitted_number=payload.submitted_number,
    )


@router.get("/demo/king-diamond/rounds/{demo_round_id}/result")
async def demo_king_diamond_result(
    demo_round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_team: Team = Depends(get_current_team),
):
    return await demo_service.king_diamond_result(
        db, demo_round_id=demo_round_id, team_id=current_team.team_id
    )


@router.post("/demo/jack-heart/rounds/{demo_round_id}/submit", status_code=status.HTTP_201_CREATED)
async def submit_demo_jack_heart(
    demo_round_id: uuid.UUID,
    payload: DemoJackHeartSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_team: Team = Depends(get_current_team),
):
    return await demo_service.submit_jack_heart(
        db,
        demo_round_id=demo_round_id,
        team_id=current_team.team_id,
        submitted_symbol_id=payload.submitted_symbol_id,
    )


@router.get("/demo/jack-heart/rounds/{demo_round_id}/visible-symbols", response_model=list)
async def demo_jack_heart_visible_symbols(
    demo_round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_team: Team = Depends(get_current_team),
):
    """Every *other* team's practice card — never the caller's own, the same
    guarantee the real endpoint makes."""
    return await demo_service.jack_heart_visible_symbols(
        db, demo_round_id=demo_round_id, team_id=current_team.team_id
    )


@router.get("/demo/jack-heart/rounds/{demo_round_id}/my-suit")
async def demo_jack_heart_my_suit(
    demo_round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_team: Team = Depends(get_current_team),
):
    return await demo_service.jack_heart_my_suit(
        db, demo_round_id=demo_round_id, team_id=current_team.team_id
    )


@router.get("/demo/rooms/{room_id}/{game_code}/leaderboard", response_model=list)
async def demo_room_leaderboard(
    room_id: uuid.UUID,
    game_code: str,
    db: AsyncSession = Depends(get_db),
    current_team: Team = Depends(get_current_team),
):
    """Practice standings only — these numbers exist nowhere but Redis and
    never reach `room_results` or the live scoreboard."""
    return await demo_service.demo_leaderboard(
        db, room_id=room_id, game_code=game_code.upper(), team_id=current_team.team_id
    )
