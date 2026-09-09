import logging
import uuid
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("round1.sessions")

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import assert_admin_room_access, get_current_admin, get_current_team, require_role
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.db.session import get_db
from app.models.admin import Admin, AdminRole
from app.models.game import Game, GameSession, SessionStatus, TeamViewAck
from app.models.round import Room
from app.models.selection import Round1Selection
from app.models.team import Team
from app.schemas.session import (
    RoomFanOutFailure,
    RoomFanOutSuccess,
    RoundStatusEntry,
    SessionDeadlineUpdate,
    SessionFanOutOut,
    SessionOut,
    SessionRoundOut,
    SessionStartRequest,
    SessionWithRoundsOut,
    TeamSubmissionDetail,
    ViewAckRequest,
)
from app.services import session_service
from app.workers import jobs
from app.workers.scheduler import cancel_round_close, schedule_round_close

router = APIRouter(tags=["sessions"])


def _make_round_status_entry(
    r,
    game_code: str,
    now: datetime,
    submissions_map: dict | None = None,
) -> RoundStatusEntry:
    is_closed = r.deadline is not None and r.deadline <= now
    if game_code == "KING_DIAMOND":
        is_closed = is_closed or getattr(r, "is_closed", False)

    submitted = False
    score = None
    mistakes = None
    correct_tiles = None
    correct_picks = None
    wrong_picks = None

    if submissions_map and r.round_id in submissions_map:
        submitted = True
        sub_obj = submissions_map[r.round_id]
        score = getattr(sub_obj, "round_score", None)
        mistakes = getattr(sub_obj, "mistakes", None)
        correct_tiles = getattr(sub_obj, "correct_tiles", None)
        correct_picks = getattr(sub_obj, "correct_picks", None)
        wrong_picks = getattr(sub_obj, "wrong_picks", None)

    return RoundStatusEntry(
        round_number=r.round_number,
        round_id=r.round_id,
        deadline=r.deadline,
        is_closed=bool(is_closed),
        submitted=submitted,
        score=float(score) if score is not None else None,
        mistakes=mistakes,
        correct_tiles=correct_tiles,
        correct_picks=correct_picks,
        wrong_picks=wrong_picks,
        start_time=getattr(r, "start_time", None),
    )


@router.post(
    "/admin/rooms/{room_id}/sessions/{game_code}/start",
    response_model=SessionWithRoundsOut,
    status_code=status.HTTP_201_CREATED,
)
async def start_session(
    room_id: uuid.UUID,
    game_code: str,
    payload: SessionStartRequest,
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    assert_admin_room_access(admin, room_id)  # §2.9
    session, rounds = await session_service.start_session(
        db,
        room_id=room_id,
        game_code=game_code.upper(),
        duration_minutes=payload.duration_minutes,
        num_rounds=payload.rounds,
    )

    # Registers a scheduler job per round to auto-close it at its deadline.
    for round_row in rounds:
        if round_row.deadline is not None:
            schedule_round_close(game_code.upper(), round_row.round_id, round_row.deadline)

    return SessionWithRoundsOut(
        session=SessionOut.model_validate(session),
        rounds=[
            _make_round_status_entry(r, game_code.upper(), datetime.now(timezone.utc))
            for r in rounds
        ],
    )


@router.get("/rooms/{room_id}/sessions", response_model=list[SessionOut])
async def list_room_sessions(
    room_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_team: Team = Depends(get_current_team),
):
    # Audit Issue 7: previously any authenticated team could query any
    # room_id, leaking the game lineup, session statuses, and round
    # deadlines for rooms they don't belong to. Only allow a team to see
    # sessions for the room it is actually assigned to.
    selection = (
        await db.execute(
            select(Round1Selection).where(
                Round1Selection.team_id == current_team.team_id,
                Round1Selection.room_id == room_id,
            )
        )
    ).scalar_one_or_none()
    if selection is None:
        raise ForbiddenError("Your team is not assigned to this room")

    sessions = (await db.execute(select(GameSession).where(GameSession.room_id == room_id))).scalars().all()
    games = {g.game_id: g.code for g in (await db.execute(select(Game))).scalars().all()}
    out = []
    for session in sessions:
        game_code = games.get(session.game_id)
        round_model = session_service._ROUND_MODEL_BY_GAME_CODE.get(game_code)
        rounds = []
        if round_model is not None:
            round_rows = (
                (await db.execute(select(round_model).where(round_model.session_id == session.session_id)))
                .scalars()
                .all()
            )
            submissions_map = {}
            now = datetime.now(timezone.utc)
            if round_rows:
                r_ids = [row.round_id for row in round_rows]
                if game_code == "MINDMAZE":
                    from app.models.mindmaze import MindmazeResult
                    results = (
                        await db.execute(
                            select(MindmazeResult).where(
                                MindmazeResult.round_id.in_(r_ids),
                                MindmazeResult.team_id == current_team.team_id,
                            )
                        )
                    ).scalars().all()
                    submissions_map = {res.round_id: res for res in results}
                elif game_code == "ACE_SPADE":
                    from app.models.ace_spade import AceSpadeResult
                    results = (
                        await db.execute(
                            select(AceSpadeResult).where(
                                AceSpadeResult.round_id.in_(r_ids),
                                AceSpadeResult.team_id == current_team.team_id,
                            )
                        )
                    ).scalars().all()
                    submissions_map = {res.round_id: res for res in results}
                elif game_code == "JACK_HEART":
                    from app.models.jack_heart import JackHeartAnswer
                    results = (
                        await db.execute(
                            select(JackHeartAnswer).where(
                                JackHeartAnswer.round_id.in_(r_ids),
                                JackHeartAnswer.team_id == current_team.team_id,
                            )
                        )
                    ).scalars().all()
                    submissions_map = {res.round_id: res for res in results}
                elif game_code == "KING_DIAMOND":
                    from app.models.king_diamond import KingDiamondSubmission
                    results = (
                        await db.execute(
                            select(KingDiamondSubmission).where(
                                KingDiamondSubmission.round_id.in_(r_ids),
                                KingDiamondSubmission.team_id == current_team.team_id,
                            )
                        )
                    ).scalars().all()
                    submissions_map = {res.round_id: res for res in results}

            for r in sorted(round_rows, key=lambda x: x.round_number):
                rounds.append(
                    _make_round_status_entry(r, game_code, now, submissions_map)
                )
        s_out = SessionOut.model_validate(session)
        s_out.game_code = game_code
        s_out.rounds = rounds
        out.append(s_out)
    return out


# ---------------------------------------------------------------------------
# §2.5 Session Configuration & Control (admin)
# ---------------------------------------------------------------------------


@router.get("/admin/rooms/{room_id}/sessions", response_model=list[SessionRoundOut])
async def admin_list_room_sessions(
    room_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    """Every session in a room with round-level statuses and deadlines, for
    the admin dashboard — unlike the team-facing endpoint above, this is
    not scoped to a single team's own room."""
    assert_admin_room_access(admin, room_id)  # §2.9
    sessions = (await db.execute(select(GameSession).where(GameSession.room_id == room_id))).scalars().all()
    out = []
    now = datetime.now(timezone.utc)
    for session in sessions:
        game = await db.get(Game, session.game_id)
        round_model = session_service._ROUND_MODEL_BY_GAME_CODE.get(game.code)
        rounds = []
        if round_model is not None:
            round_rows = (
                (await db.execute(select(round_model).where(round_model.session_id == session.session_id)))
                .scalars()
                .all()
            )
            
            submissions_map = {}
            if round_rows:
                r_ids = [row.round_id for row in round_rows]
                # Query all team codes in the room
                from app.models.team import Team
                teams = (await db.execute(
                    select(Team.team_id, Team.team_code)
                    .join(Round1Selection, Round1Selection.team_id == Team.team_id)
                    .where(Round1Selection.room_id == room_id)
                )).all()
                team_code_by_id = {t.team_id: t.team_code for t in teams}

                if game.code == "MINDMAZE":
                    from app.models.mindmaze import MindmazeResult
                    results = (
                        await db.execute(
                            select(MindmazeResult.round_id, MindmazeResult.team_id).where(
                                MindmazeResult.round_id.in_(r_ids)
                            )
                        )
                    ).all()
                    for round_id, team_id in results:
                        code = team_code_by_id.get(team_id)
                        if code:
                            submissions_map.setdefault(round_id, []).append(code)
                elif game.code == "ACE_SPADE":
                    from app.models.ace_spade import AceSpadeResult
                    results = (
                        await db.execute(
                            select(AceSpadeResult.round_id, AceSpadeResult.team_id).where(
                                AceSpadeResult.round_id.in_(r_ids)
                            )
                        )
                    ).all()
                    for round_id, team_id in results:
                        code = team_code_by_id.get(team_id)
                        if code:
                            submissions_map.setdefault(round_id, []).append(code)
                elif game.code == "JACK_HEART":
                    from app.models.jack_heart import JackHeartAnswer
                    results = (
                        await db.execute(
                            select(JackHeartAnswer.round_id, JackHeartAnswer.team_id).where(
                                JackHeartAnswer.round_id.in_(r_ids)
                            )
                        )
                    ).all()
                    for round_id, team_id in results:
                        code = team_code_by_id.get(team_id)
                        if code:
                            submissions_map.setdefault(round_id, []).append(code)
                elif game.code == "KING_DIAMOND":
                    from app.models.king_diamond import KingDiamondSubmission
                    results = (
                        await db.execute(
                            select(KingDiamondSubmission.round_id, KingDiamondSubmission.team_id).where(
                                KingDiamondSubmission.round_id.in_(r_ids)
                            )
                        )
                    ).all()
                    for round_id, team_id in results:
                        code = team_code_by_id.get(team_id)
                        if code:
                            submissions_map.setdefault(round_id, []).append(code)

            for r in sorted(round_rows, key=lambda r: r.round_number):
                entry = _make_round_status_entry(r, game.code, now)
                entry.submitted_teams = submissions_map.get(r.round_id, [])
                rounds.append(entry)

        out.append(SessionRoundOut(session=SessionOut.model_validate(session), game_code=game.code, rounds=rounds))
    return out


@router.post("/admin/sessions/{session_id}/force-complete", status_code=status.HTTP_204_NO_CONTENT)
async def force_complete_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    """Audit Issue 3 escape hatch: mark a session COMPLETED and trigger the
    room-close check manually, for use when the scheduler job that should
    have done this was lost (e.g. before the RedisJobStore fix, or a
    misfire that exceeded its grace period)."""
    session = await db.get(GameSession, session_id)
    if session is None:
        raise NotFoundError("Session not found")
    assert_admin_room_access(admin, session.room_id)  # §2.9
    if session.status == SessionStatus.PAUSED:
        raise ConflictError("Resume the session before force-completing it.")
    await jobs._maybe_close_session(session_id, force=True)


@router.post("/admin/sessions/{session_id}/show-instructions", status_code=status.HTTP_204_NO_CONTENT)
async def show_game_instructions(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    """Admin triggers a 5-minute instruction display on all team screens
    for this game session. Works regardless of session status — useful
    before the game starts, between rounds, or as a refresher mid-game."""
    session = await db.get(GameSession, session_id)
    if session is None:
        raise NotFoundError("Session not found")
    assert_admin_room_access(admin, session.room_id)  # §2.9

    session.instruction_until = datetime.now(timezone.utc) + timedelta(minutes=5)
    await db.commit()


@router.post("/admin/sessions/{session_id}/pause", response_model=SessionWithRoundsOut)
async def pause_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    """IN_PROGRESS -> PAUSED. Cancels the pending close-job for every round
    that hasn't hit its deadline yet so nothing auto-closes mid-pause."""
    existing = await db.get(GameSession, session_id)
    if existing is None:
        raise NotFoundError("Session not found")
    assert_admin_room_access(admin, existing.room_id)  # §2.9

    session, open_rounds = await session_service.pause_session(db, session_id=session_id)
    game = await db.get(Game, session.game_id)
    for round_row in open_rounds:
        cancel_round_close(game.code, round_row.round_id)

    return SessionWithRoundsOut(
        session=SessionOut.model_validate(session),
        rounds=[
            _make_round_status_entry(r, game.code, datetime.now(timezone.utc))
            for r in open_rounds
        ],
    )


@router.post("/admin/sessions/{session_id}/resume", response_model=SessionWithRoundsOut)
async def resume_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    """PAUSED -> IN_PROGRESS. Every round that was still open gets its
    deadline pushed back by however long the pause lasted, and its
    close-job re-registered at the new deadline."""
    existing = await db.get(GameSession, session_id)
    if existing is None:
        raise NotFoundError("Session not found")
    assert_admin_room_access(admin, existing.room_id)  # §2.9

    session, extended_rounds = await session_service.resume_session(db, session_id=session_id)
    game = await db.get(Game, session.game_id)
    for round_row in extended_rounds:
        schedule_round_close(game.code, round_row.round_id, round_row.deadline)

    return SessionWithRoundsOut(
        session=SessionOut.model_validate(session),
        rounds=[
            _make_round_status_entry(r, game.code, datetime.now(timezone.utc))
            for r in extended_rounds
        ],
    )


@router.post("/admin/sessions/{session_id}/restart", response_model=SessionOut)
async def restart_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    # Destructive: wipes every round + score row for this session. Restricted
    # to SUPER_ADMIN, same bar as force-complete and deadline overrides.
    admin: Admin = Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    """Resets a session back to NOT_STARTED so it can be started fresh —
    deletes its round rows and game_scores rows and clears its contribution
    to the room leaderboard. Irreversible."""
    session_before = await db.get(GameSession, session_id)
    if session_before is None:
        raise NotFoundError("Session not found")
    assert_admin_room_access(admin, session_before.room_id)  # §2.9
    game = await db.get(Game, session_before.game_id)
    game_code = game.code  # capture plain string — restart_session commits internally

    session, round_ids = await session_service.restart_session(db, session_id=session_id)
    for round_id in round_ids:
        cancel_round_close(game_code, round_id)

    return SessionOut.model_validate(session)


@router.patch(
    "/admin/sessions/{session_id}/rounds/{round_number}/deadline", response_model=RoundStatusEntry
)
async def update_round_deadline(
    session_id: uuid.UUID,
    round_number: int,
    payload: SessionDeadlineUpdate,
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    """Extend or shorten a round's deadline, and re-register the scheduler
    job to match — pairs with DELETE /admin/scheduler/jobs/{job_id} if the
    old job needs cancelling first."""
    session = await db.get(GameSession, session_id)
    if session is None:
        raise NotFoundError("Session not found")
    assert_admin_room_access(admin, session.room_id)  # §2.9
    if session.status == SessionStatus.PAUSED:
        raise ConflictError(
            "Cannot update a round deadline while the session is paused — resume first, "
            "or use the resume endpoint which shifts all open deadlines automatically."
        )

    game = await db.get(Game, session.game_id)
    round_model = session_service._ROUND_MODEL_BY_GAME_CODE.get(game.code)
    if round_model is None:
        raise NotFoundError(f"Unknown game_code '{game.code}'")

    round_obj = (
        await db.execute(
            select(round_model).where(
                round_model.session_id == session_id, round_model.round_number == round_number
            )
        )
    ).scalar_one_or_none()
    if round_obj is None:
        raise NotFoundError("Round not found for this session")

    round_obj.deadline = payload.new_deadline
    await db.commit()
    await db.refresh(round_obj)

    schedule_round_close(game.code, round_obj.round_id, payload.new_deadline)

    return _make_round_status_entry(round_obj, game.code, datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# §1 — Round-scoped, cross-room control ("start MindMaze everywhere")
#
# Purely additive on top of the per-room endpoints above: none of them
# change, and these reuse the exact same single-room service functions
# internally (see session_service.py's "§1" section), so single-room
# control (e.g. "restart just Room 4" for adjudication) still works
# unchanged. Restricted to SUPER_ADMIN — a ROOM_ADMIN bound to one room
# (§2.9) has no business starting/stopping a game in every room at once.
# ---------------------------------------------------------------------------


def _fan_out_response(game_code: str, round_id: uuid.UUID, results: list[dict]) -> SessionFanOutOut:
    import asyncio
    from app.workers.jobs import _publish

    succeeded, failed = [], []
    for r in results:
        if r["ok"]:
            session_id = r["session"].session_id if "session" in r else r["session_id"]
            succeeded.append(RoomFanOutSuccess(room_id=r["room_id"], room_code=r["room_code"], session_id=session_id))
            try:
                asyncio.create_task(_publish(f"room:{r['room_id']}:sessions"))
            except Exception:
                pass
        else:
            failed.append(RoomFanOutFailure(room_id=r["room_id"], room_code=r["room_code"], reason=r["reason"]))
    return SessionFanOutOut(game_code=game_code, round_id=round_id, succeeded=succeeded, failed=failed)



@router.post(
    "/admin/rounds/{round_id}/sessions/{game_code}/start",
    response_model=SessionFanOutOut,
    status_code=status.HTTP_207_MULTI_STATUS,
)
async def start_session_for_round(
    round_id: uuid.UUID,
    game_code: str,
    payload: SessionStartRequest,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    """Starts game_code in every room in this round whose configured
    lineup includes it. Registers a scheduler close-job per successfully
    created round, exactly as the per-room start endpoint does."""
    game_code = game_code.upper()
    results = await session_service.start_session_for_round(
        db,
        round_id=round_id,
        game_code=game_code,
        duration_minutes=payload.duration_minutes,
        num_rounds=payload.rounds,
    )
    for r in results:
        if r["ok"]:
            for round_row in r["rounds"]:
                schedule_round_close(game_code, round_row.round_id, round_row.deadline)
    return _fan_out_response(game_code, round_id, results)


@router.post(
    "/admin/rounds/{round_id}/sessions/{game_code}/pause",
    response_model=SessionFanOutOut,
    status_code=status.HTTP_207_MULTI_STATUS,
)
async def pause_sessions_for_round(
    round_id: uuid.UUID,
    game_code: str,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    game_code = game_code.upper()
    results = await session_service.pause_sessions_for_round(db, round_id=round_id, game_code=game_code)
    for r in results:
        if r["ok"]:
            for round_row in r["rounds"]:
                cancel_round_close(game_code, round_row.round_id)
    return _fan_out_response(game_code, round_id, results)


@router.post(
    "/admin/rounds/{round_id}/sessions/{game_code}/resume",
    response_model=SessionFanOutOut,
    status_code=status.HTTP_207_MULTI_STATUS,
)
async def resume_sessions_for_round(
    round_id: uuid.UUID,
    game_code: str,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    game_code = game_code.upper()
    results = await session_service.resume_sessions_for_round(db, round_id=round_id, game_code=game_code)
    return _fan_out_response(game_code, round_id, results)


@router.post(
    "/admin/rounds/{round_id}/sessions/{game_code}/restart",
    response_model=SessionFanOutOut,
    status_code=status.HTTP_207_MULTI_STATUS,
)
async def restart_sessions_for_round(
    round_id: uuid.UUID,
    game_code: str,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    """Destructive per room, same as the single-room restart endpoint."""
    game_code = game_code.upper()
    results = await session_service.restart_sessions_for_round(db, round_id=round_id, game_code=game_code)
    for r in results:
        if r["ok"]:
            for game_round_id in r["rounds"]:
                cancel_round_close(game_code, game_round_id)
    return _fan_out_response(game_code, round_id, results)


@router.post(
    "/admin/rounds/{round_id}/sessions/{game_code}/force-complete",
    response_model=SessionFanOutOut,
    status_code=status.HTTP_207_MULTI_STATUS,
)
async def force_complete_sessions_for_round(
    round_id: uuid.UUID,
    game_code: str,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    game_code = game_code.upper()
    results = await session_service.force_complete_sessions_for_round(db, round_id=round_id, game_code=game_code)
    return _fan_out_response(game_code, round_id, results)


@router.post(
    "/admin/rounds/{round_id}/sessions/{game_code}/show-instructions",
    response_model=SessionFanOutOut,
    status_code=status.HTTP_207_MULTI_STATUS,
)
async def show_instructions_for_round(
    round_id: uuid.UUID,
    game_code: str,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    game_code = game_code.upper()
    results = await session_service.show_instructions_for_round(db, round_id=round_id, game_code=game_code)
    return _fan_out_response(game_code, round_id, results)


@router.post(
    "/admin/rounds/{round_id}/sessions/{game_code}/start-next-subround",
    response_model=SessionFanOutOut,
    status_code=status.HTTP_207_MULTI_STATUS,
)
async def start_next_subround_for_round(
    round_id: uuid.UUID,
    game_code: str,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    game_code = game_code.upper()
    results = await session_service.start_next_subround_for_round(db, round_id=round_id, game_code=game_code)
    return _fan_out_response(game_code, round_id, results)


@router.post(
    "/admin/rounds/{round_id}/sessions/{game_code}/subrounds/{subround_number}/start",
    response_model=SessionFanOutOut,
    status_code=status.HTTP_207_MULTI_STATUS,
)
async def start_subround_by_number_for_round(
    round_id: uuid.UUID,
    game_code: str,
    subround_number: int,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    game_code = game_code.upper()
    results = await session_service.start_subround_by_number_for_round(
        db, round_id=round_id, game_code=game_code, subround_number=subround_number
    )
    return _fan_out_response(game_code, round_id, results)


@router.post(
    "/admin/rounds/{round_id}/sessions/{game_code}/subrounds/{subround_number}/restart",
    response_model=SessionFanOutOut,
    status_code=status.HTTP_207_MULTI_STATUS,
)
async def restart_subround_by_number_for_round(
    round_id: uuid.UUID,
    game_code: str,
    subround_number: int,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    game_code = game_code.upper()
    results = await session_service.restart_subround_by_number_for_round(
        db, round_id=round_id, game_code=game_code, subround_number=subround_number
    )
    return _fan_out_response(game_code, round_id, results)


@router.post(
    "/admin/rounds/{round_id}/sessions/{game_code}/subrounds/{subround_number}/pause",
    response_model=SessionFanOutOut,
    status_code=status.HTTP_207_MULTI_STATUS,
)
async def pause_subround_by_number_for_round(
    round_id: uuid.UUID,
    game_code: str,
    subround_number: int,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    game_code = game_code.upper()
    results = await session_service.pause_subround_by_number_for_round(
        db, round_id=round_id, game_code=game_code, subround_number=subround_number
    )
    return _fan_out_response(game_code, round_id, results)


@router.post(
    "/admin/rounds/{round_id}/sessions/{game_code}/publish-results",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def publish_game_results_for_round(
    round_id: uuid.UUID,
    game_code: str,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    """Publishes results for ONLY this specific game_code across all rooms in this round.
    Allows teams to view that game's scores without triggering final round qualification."""
    game_code = game_code.upper()
    from app.models.game import Game, GameSession
    from app.models.round import Room

    game = (await db.execute(select(Game).where(Game.code == game_code))).scalar_one_or_none()
    if game is None:
        raise NotFoundError(f"Unknown game '{game_code}'")

    sessions = (
        await db.execute(
            select(GameSession).where(
                GameSession.round_id == round_id,
                GameSession.game_id == game.game_id,
            )
        )
    ).scalars().all()

    for s in sessions:
        s.is_published = True
        s.status = SessionStatus.COMPLETED
    await db.commit()

    from app.services import results_service

    rooms = (await db.execute(select(Room).where(Room.round_id == round_id))).scalars().all()
    for r in rooms:
        try:
            await results_service.recompute_room_results(db, room_id=r.room_id)
        except Exception as exc:
            logger.warning("Error recomputing room results for room %s: %s", r.room_id, exc)

    for r in rooms:
        await jobs._publish(f"room:{r.room_id}:sessions")
        await jobs._publish(f"room:{r.room_id}:leaderboard")
    await jobs._publish("leaderboard:overall")


@router.post("/sessions/{session_id}/view-ack", status_code=status.HTTP_204_NO_CONTENT)
async def acknowledge_session_view(
    session_id: uuid.UUID,
    payload: ViewAckRequest,
    db: AsyncSession = Depends(get_db),
    current_team: Team = Depends(get_current_team),
):
    session = await db.get(GameSession, session_id)
    if session is None:
        raise NotFoundError("Session not found")

    cond = [
        TeamViewAck.session_id == session_id,
        TeamViewAck.team_id == current_team.team_id,
        TeamViewAck.view_type == payload.view_type,
    ]
    if payload.round_id is not None:
        cond.append(TeamViewAck.round_id == payload.round_id)
    else:
        cond.append(TeamViewAck.round_id.is_(None))

    existing = (await db.execute(select(TeamViewAck).where(*cond))).scalars().first()

    if not existing:
        ack = TeamViewAck(
            session_id=session_id,
            team_id=current_team.team_id,
            view_type=payload.view_type,
            round_id=payload.round_id,
        )
        db.add(ack)
        await db.commit()
        await jobs._publish(f"room:{session.room_id}:sessions")

    return None


@router.get("/admin/rounds/{round_id}/game-sessions", response_model=list[SessionRoundOut])
async def admin_list_round_game_sessions(
    round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: Admin = Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    rooms = (await db.execute(select(Room).where(Room.round_id == round_id))).scalars().all()
    if not rooms:
        return []

    room_ids = [r.room_id for r in rooms]
    room_code_by_id = {r.room_id: (getattr(r, "room_code", None) or f"Room {r.room_number}") for r in rooms}
    sessions = (await db.execute(select(GameSession).where(GameSession.room_id.in_(room_ids)))).scalars().all()

    all_teams_list = (await db.execute(select(Team))).scalars().all()
    team_by_id = {t.team_id: t for t in all_teams_list}

    selections = (
        await db.execute(
            select(Round1Selection.team_id, Round1Selection.room_id)
            .where(Round1Selection.room_id.in_(room_ids))
        )
    ).all()
    teams_by_room: dict[uuid.UUID, list] = {}
    for sel in selections:
        t_obj = team_by_id.get(sel.team_id)
        if t_obj:
            teams_by_room.setdefault(sel.room_id, []).append(t_obj)

    # Pre-fetch all view acks for these sessions
    session_ids = [s.session_id for s in sessions]
    view_acks = (
        await db.execute(select(TeamViewAck).where(TeamViewAck.session_id.in_(session_ids)))
    ).scalars().all()
    published_views_by_session: dict[uuid.UUID, set[str]] = {}
    midgame_views_by_round: dict[uuid.UUID, set[str]] = {}
    for v in view_acks:
        t_obj = team_by_id.get(v.team_id)
        t_code = t_obj.team_code if t_obj else str(v.team_id)
        if v.view_type == "PUBLISHED_RESULTS":
            published_views_by_session.setdefault(v.session_id, set()).add(t_code)
        elif v.view_type == "JH_MID_GAME" and v.round_id:
            midgame_views_by_round.setdefault(v.round_id, set()).add(t_code)

    out = []
    now = datetime.now(timezone.utc)
    for session in sessions:
        game = await db.get(Game, session.game_id)
        if game is None:
            continue
        round_model = session_service._ROUND_MODEL_BY_GAME_CODE.get(game.code)
        rounds = []
        submissions_map: dict[uuid.UUID, list[str]] = {}
        submission_details_map: dict[uuid.UUID, list[TeamSubmissionDetail]] = {}
        is_computed_map: dict[uuid.UUID, bool] = {}

        if round_model is not None:
            round_rows = (
                (await db.execute(select(round_model).where(round_model.session_id == session.session_id)))
                .scalars()
                .all()
            )

            if round_rows:
                r_ids = [row.round_id for row in round_rows]
                if game.code == "MINDMAZE":
                    from app.models.mindmaze import MindmazeResult
                    results = (
                        await db.execute(
                            select(MindmazeResult).where(MindmazeResult.round_id.in_(r_ids))
                        )
                    ).scalars().all()
                    for res in results:
                        t_obj = team_by_id.get(res.team_id)
                        t_code = t_obj.team_code if t_obj else "—"
                        t_name = t_obj.team_name if t_obj else "—"
                        submissions_map.setdefault(res.round_id, []).append(t_code)
                        sub_time_str = res.submitted_at.strftime("%H:%M:%S") if res.submitted_at else "—"
                        sc = float(res.round_score) if res.round_score is not None else 0.0
                        tiles = res.correct_tiles if res.correct_tiles is not None else 0
                        mists = res.mistakes if res.mistakes is not None else 0
                        detail_text = f"+{sc:.0f} pts ({tiles}/20 correct, {mists} mistakes)"
                        submission_details_map.setdefault(res.round_id, []).append(
                            TeamSubmissionDetail(
                                team_id=res.team_id,
                                team_code=t_code,
                                team_name=t_name,
                                submitted_at=res.submitted_at,
                                submitted_at_str=sub_time_str,
                                score=sc,
                                detail=detail_text,
                            )
                        )

                elif game.code == "ACE_SPADE":
                    from app.models.ace_spade import AceSpadeResult
                    results = (
                        await db.execute(
                            select(AceSpadeResult).where(AceSpadeResult.round_id.in_(r_ids))
                        )
                    ).scalars().all()
                    for res in results:
                        t_obj = team_by_id.get(res.team_id)
                        t_code = t_obj.team_code if t_obj else "—"
                        t_name = t_obj.team_name if t_obj else "—"
                        submissions_map.setdefault(res.round_id, []).append(t_code)
                        sub_time_str = res.submitted_at.strftime("%H:%M:%S") if res.submitted_at else "—"
                        sc = float(res.round_score) if res.round_score is not None else 0.0
                        picks = res.correct_picks if res.correct_picks is not None else 0
                        wrongs = res.wrong_picks if res.wrong_picks is not None else 0
                        detail_text = f"+{sc:.1f} pts ({picks}/8 correct, {wrongs} wrong)"
                        submission_details_map.setdefault(res.round_id, []).append(
                            TeamSubmissionDetail(
                                team_id=res.team_id,
                                team_code=t_code,
                                team_name=t_name,
                                submitted_at=res.submitted_at,
                                submitted_at_str=sub_time_str,
                                score=sc,
                                detail=detail_text,
                            )
                        )

                elif game.code == "JACK_HEART":
                    from app.models.jack_heart import JackHeartAnswer, JHSymbol
                    answers = (
                        await db.execute(
                            select(JackHeartAnswer).where(JackHeartAnswer.round_id.in_(r_ids))
                        )
                    ).scalars().all()
                    symbols = (await db.execute(select(JHSymbol))).scalars().all()
                    symbol_by_id = {s.symbol_id: s.label for s in symbols}

                    for ans in answers:
                        t_obj = team_by_id.get(ans.team_id)
                        t_code = t_obj.team_code if t_obj else "—"
                        t_name = t_obj.team_name if t_obj else "—"
                        submissions_map.setdefault(ans.round_id, []).append(t_code)
                        sub_time_str = ans.submitted_at.strftime("%H:%M:%S") if ans.submitted_at else "—"
                        card_label = symbol_by_id.get(ans.submitted_symbol_id, f"Card #{ans.submitted_symbol_id}")
                        result_label = "Correct (+5.0)" if ans.is_correct else "Wrong (0.0)"
                        detail_text = f"Guessed: {card_label} — {result_label}"
                        sc = float(ans.round_score) if ans.round_score is not None else 0.0
                        submission_details_map.setdefault(ans.round_id, []).append(
                            TeamSubmissionDetail(
                                team_id=ans.team_id,
                                team_code=t_code,
                                team_name=t_name,
                                submitted_at=ans.submitted_at,
                                submitted_at_str=sub_time_str,
                                score=sc,
                                detail=detail_text,
                            )
                        )

                elif game.code == "KING_DIAMOND":
                    from app.models.king_diamond import KingDiamondSubmission
                    subs = (
                        await db.execute(
                            select(KingDiamondSubmission).where(KingDiamondSubmission.round_id.in_(r_ids))
                        )
                    ).scalars().all()
                    for sub in subs:
                        t_obj = team_by_id.get(sub.team_id)
                        t_code = t_obj.team_code if t_obj else "—"
                        t_name = t_obj.team_name if t_obj else "—"
                        submissions_map.setdefault(sub.round_id, []).append(t_code)
                        sub_time_str = sub.submitted_at.strftime("%H:%M:%S") if sub.submitted_at else "—"
                        num_str = f"{float(sub.submitted_number):.2f}" if sub.submitted_number is not None else "—"
                        diff_str = f"Diff: {float(sub.difference):.2f}" if sub.difference is not None else ""
                        sc = float(sub.round_score) if sub.round_score is not None else 0.0
                        pen_str = f"-{sc:.1f} pts" if sub.round_score is not None else ""
                        parts = [p for p in [diff_str, pen_str] if p]
                        bracket_info = f" ({' | '.join(parts)})" if parts else ""
                        detail_text = f"Picked: {num_str}{bracket_info}"
                        submission_details_map.setdefault(sub.round_id, []).append(
                            TeamSubmissionDetail(
                                team_id=sub.team_id,
                                team_code=t_code,
                                team_name=t_name,
                                submitted_at=sub.submitted_at,
                                submitted_at_str=sub_time_str,
                                score=sc,
                                detail=detail_text,
                            )
                        )

            for r in sorted(round_rows, key=lambda x: x.round_number):
                entry = _make_round_status_entry(r, game.code, now)
                entry.submitted_teams = submissions_map.get(r.round_id, [])
                entry.submission_details = submission_details_map.get(r.round_id, [])
                entry.viewed_teams = list(midgame_views_by_round.get(r.round_id, set()))
                entry.is_computed = bool(
                    getattr(r, "is_closed", False)
                    or (r.deadline is not None and r.deadline <= now)
                    or len(entry.submitted_teams) > 0
                )
                rounds.append(entry)

        # Compute exact active teams in room
        active_room_teams_count = 0
        active_team_codes = []
        if session.roster_team_ids:
            active_room_teams_count = len(session.roster_team_ids)
            for tid in session.roster_team_ids:
                t_obj = team_by_id.get(tid if isinstance(tid, uuid.UUID) else uuid.UUID(str(tid)))
                if t_obj:
                    active_team_codes.append(t_obj.team_code)
        elif teams_by_room.get(session.room_id):
            room_t_list = teams_by_room[session.room_id]
            active_room_teams_count = len(room_t_list)
            active_team_codes = [t.team_code for t in room_t_list if hasattr(t, "team_code")]
        else:
            all_submitted = set()
            for sub_list in submissions_map.values():
                all_submitted.update(sub_list)
            active_room_teams_count = len(all_submitted)
            active_team_codes = list(all_submitted)

        s_out = SessionOut.model_validate(session)
        s_out.game_code = game.code
        s_out.room_code = room_code_by_id.get(session.room_id)
        s_out.total_room_teams = active_room_teams_count
        s_out.published_viewed_teams = list(published_views_by_session.get(session.session_id, set()))
        s_out.active_team_codes = active_team_codes
        s_out.rounds = rounds
        out.append(SessionRoundOut(session=s_out, game_code=game.code, rounds=rounds))
    return out




