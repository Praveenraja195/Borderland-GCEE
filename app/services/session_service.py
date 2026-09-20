import random
import uuid
from datetime import datetime, timedelta, timezone


from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError
from app.db.session import async_session_maker
from app.models.ace_spade import AceSpadeRound
from app.models.game import Game, GameScore, GameSession, RoundGames, SessionStatus
from app.models.jack_heart import JackHeartAssignment, JackHeartRound, JHSymbol
from app.models.king_diamond import KingDiamondRound
from app.models.mindmaze import MindmazeRound
from app.models.round import Room, RoomStatus
from app.models.selection import Round1Selection, Suit

# A sub-round never starts "now": it is scheduled this far ahead so every
# device has time to receive the update and count down to the same server
# instant (the team app derives its 5-4-3-2-1 from start_time and the synced
# server clock, not from when the message arrived).
SUBROUND_START_LEAD = timedelta(seconds=5)

_ROUND_MODEL_BY_GAME_CODE = {
    "MINDMAZE": MindmazeRound,
    "ACE_SPADE": AceSpadeRound,
    "KING_DIAMOND": KingDiamondRound,
    "JACK_HEART": JackHeartRound,
}


async def start_session(
    db: AsyncSession,
    *,
    room_id: uuid.UUID,
    game_code: str,
    duration_minutes: int,
    num_rounds: int,
) -> tuple[GameSession, list]:
    room = await db.get(Room, room_id)
    if room is None:
        raise NotFoundError("Room not found")

    game = (await db.execute(select(Game).where(Game.code == game_code))).scalar_one_or_none()
    if game is None:
        raise NotFoundError(f"Unknown game_code '{game_code}'")

    existing = (
        await db.execute(
            select(GameSession).where(GameSession.room_id == room_id, GameSession.game_id == game.game_id)
        )
    ).scalar_one_or_none()
    if existing is not None and existing.status != SessionStatus.NOT_STARTED:
        raise ConflictError(f"Session for {game_code} in this room already {existing.status.value}")

    session = existing or GameSession(round_id=room.round_id, room_id=room_id, game_id=game.game_id)
    session.status = SessionStatus.IN_PROGRESS
    session.start_time = datetime.now(timezone.utc)
    session.is_published = False

    # Audit §2.6: snapshot exactly who's in the room right now. Close jobs
    # roll up against this list instead of re-querying round1_selections at
    # close time, so a team moved in/out of the room after this point (see
    # admin_service.move_team_room) can't desync the roster used to
    # backfill no-submit rows from the roster that actually played.
    roster_team_ids = (
        (await db.execute(select(Round1Selection.team_id).where(Round1Selection.room_id == room_id)))
        .scalars()
        .all()
    )
    session.roster_team_ids = [str(t) for t in roster_team_ids]

    db.add(session)
    await db.flush()

    round_model = _ROUND_MODEL_BY_GAME_CODE.get(game_code)
    if round_model is None:
        raise NotFoundError(f"No round model registered for game_code '{game_code}'")
    now = datetime.now(timezone.utc)
    rounds = []

    start_time_1 = now + SUBROUND_START_LEAD
    if game_code == "MINDMAZE":
        play = timedelta(seconds=settings.mindmaze_round_seconds)
    elif game_code == "ACE_SPADE":
        play = timedelta(seconds=settings.ace_spade_round_seconds)
    elif game_code == "KING_DIAMOND":
        # Aug 2026: fixed 45s auto-submit pacing, same reasoning as MindMaze
        # above — see settings.king_diamond_round_seconds.
        play = timedelta(seconds=settings.king_diamond_round_seconds)
    else:
        play = timedelta(minutes=duration_minutes)

    for i in range(1, num_rounds + 1):
        if i == 1:
            st = start_time_1
            dl = st + play
        else:
            st = None
            dl = None
        round_row = round_model(
            session_id=session.session_id,
            round_number=i,
            start_time=st,
            deadline=dl,
        )
        db.add(round_row)
        rounds.append(round_row)

    await db.flush()

    if game_code == "JACK_HEART":
        await _assign_symbols(db, room_id=room_id, jh_rounds=rounds)

    await db.commit()
    for r in rounds:
        await db.refresh(r)
    await db.refresh(session)
    return session, rounds


async def _get_session_and_rounds(
    db: AsyncSession, session_id: uuid.UUID
) -> tuple[GameSession, Game, type]:
    session = await db.get(GameSession, session_id)
    if session is None:
        raise NotFoundError("Session not found")
    game = await db.get(Game, session.game_id)
    round_model = _ROUND_MODEL_BY_GAME_CODE.get(game.code)
    if round_model is None:
        raise NotFoundError(f"Unknown game_code '{game.code}'")
    return session, game, round_model


async def pause_session(db: AsyncSession, *, session_id: uuid.UUID) -> tuple[GameSession, list]:
    """IN_PROGRESS -> PAUSED. Returns the session plus every round that is
    still open (deadline not yet reached) so the caller can cancel their
    scheduler close-jobs — a job firing while paused would close a round
    the teams never got to finish."""
    session, game, round_model = await _get_session_and_rounds(db, session_id)
    if session.status != SessionStatus.IN_PROGRESS:
        raise ConflictError(f"Session for {game.code} is {session.status.value}, not IN_PROGRESS")

    now = datetime.now(timezone.utc)
    open_rounds = (
        (
            await db.execute(
                select(round_model).where(round_model.session_id == session_id, round_model.deadline > now)
            )
        )
        .scalars()
        .all()
    )

    session.status = SessionStatus.PAUSED
    session.paused_at = now
    await db.commit()
    await db.refresh(session)
    return session, open_rounds


async def resume_session(db: AsyncSession, *, session_id: uuid.UUID) -> tuple[GameSession, list]:
    """PAUSED -> IN_PROGRESS. Pushes every round that was still open when the
    session was paused forward by however long the pause lasted, so teams
    get back the time they lost. Returns the session plus those rounds so
    the caller can re-register scheduler jobs at the new deadlines."""
    session, game, round_model = await _get_session_and_rounds(db, session_id)
    if session.status == SessionStatus.IN_PROGRESS:
        all_rounds = (await db.execute(select(round_model).where(round_model.session_id == session_id))).scalars().all()
        return session, list(all_rounds)
    if session.status != SessionStatus.PAUSED:
        raise ConflictError(f"Session for {game.code} is {session.status.value}, not PAUSED")

    paused_at = session.paused_at or datetime.now(timezone.utc)
    now_utc = datetime.now(timezone.utc)
    pause_duration = now_utc - paused_at

    all_session_rounds = (
        (
            await db.execute(
                select(round_model).where(round_model.session_id == session_id)
            )
        )
        .scalars()
        .all()
    )

    extended_rounds = []
    for round_row in all_session_rounds:
        is_closed = getattr(round_row, "is_closed", False)
        if round_row.start_time is not None and not is_closed:
            if round_row.deadline is not None:
                new_deadline = round_row.deadline + pause_duration
                if new_deadline <= now_utc:
                    new_deadline = now_utc + timedelta(seconds=60)
                round_row.deadline = new_deadline

            round_row.start_time = round_row.start_time + pause_duration
            extended_rounds.append(round_row)

    session.status = SessionStatus.IN_PROGRESS
    session.paused_at = None
    await db.commit()
    for r in all_session_rounds:
        await db.refresh(r)
    await db.refresh(session)

    from app.workers.scheduler import schedule_round_close
    for r in extended_rounds:
        if r.deadline is not None:
            schedule_round_close(game.code, r.round_id, r.deadline)

    return session, extended_rounds


async def restart_session(db: AsyncSession, *, session_id: uuid.UUID) -> tuple[GameSession, list]:
    """Destructive reset: wipes every round and score row for this session
    and puts it back to NOT_STARTED so `start_session` can be called again
    as if the session never ran. Intended for SUPER_ADMIN only — callers
    are responsible for enforcing that at the route layer.

    Returns the reset session plus the round_ids that existed before the
    wipe, so the caller can cancel any scheduler jobs still registered for
    them (the rows they pointed at no longer exist)."""
    session, game, round_model = await _get_session_and_rounds(db, session_id)
    if session.status == SessionStatus.NOT_STARTED:
        return session, []

    round_ids = (
        (await db.execute(select(round_model.round_id).where(round_model.session_id == session_id)))
        .scalars()
        .all()
    )

    await db.execute(delete(round_model).where(round_model.session_id == session_id))
    await db.execute(delete(GameScore).where(GameScore.session_id == session_id))

    session.status = SessionStatus.NOT_STARTED
    session.start_time = None
    session.end_time = None
    session.paused_at = None
    session.is_published = False
    await db.flush()

    # A restarted session can no longer count as COMPLETED, so a room that
    # had already been marked fully done needs to drop back to ACTIVE.
    room = await db.get(Room, session.room_id)
    if room is not None and room.status == RoomStatus.COMPLETED:
        room.status = RoomStatus.ACTIVE

    await db.commit()
    await db.refresh(session)

    return session, list(round_ids)


async def recover_scheduler_jobs(db: AsyncSession) -> int:
    """Startup safety net (Issue 10): if the process crashed between
    committing a deadline change and registering the matching scheduler
    job — e.g. between resume_session's commit and the route's
    schedule_round_close call — the round would silently never auto-close,
    since RedisJobStore only has what actually got registered.

    Scans every IN_PROGRESS session's still-open rounds and re-registers
    any close-job missing from the scheduler. Safe to call on every
    startup: scheduler.add_job(..., replace_existing=True) means an
    already-registered job is a no-op. Returns the number of jobs
    recovered, for startup logging."""
    from app.workers.scheduler import schedule_round_close, scheduler

    now = datetime.now(timezone.utc)
    sessions = (
        (await db.execute(select(GameSession).where(GameSession.status == SessionStatus.IN_PROGRESS)))
        .scalars()
        .all()
    )

    recovered = 0
    for session in sessions:
        game = await db.get(Game, session.game_id)
        round_model = _ROUND_MODEL_BY_GAME_CODE.get(game.code)
        if round_model is None:
            continue
        open_rounds = (
            (
                await db.execute(
                    select(round_model).where(
                        round_model.session_id == session.session_id, round_model.deadline > now
                    )
                )
            )
            .scalars()
            .all()
        )
        for round_row in open_rounds:
            job_id = f"close_{game.code.lower()}_{round_row.round_id}"
            if scheduler.get_job(job_id) is None:
                schedule_round_close(game.code, round_row.round_id, round_row.deadline)
                recovered += 1
    return recovered


async def _assign_symbols(db: AsyncSession, *, room_id: uuid.UUID, jh_rounds: list[JackHeartRound]) -> None:
    """One symbol assignment per team per round, drawn fresh each round
    from each team's respective suit so each team's card is strictly from their suit."""
    team_ids = (
        (await db.execute(select(Round1Selection.team_id).where(Round1Selection.room_id == room_id)))
        .scalars()
        .all()
    )
    if not team_ids:
        return

    team_suits = (
        await db.execute(
            select(Round1Selection.team_id, Suit.code)
            .join(Suit, Suit.suit_id == Round1Selection.suit_id)
            .where(Round1Selection.team_id.in_(team_ids))
        )
    ).all()
    team_suit_map = {t_id: (s_code.upper() if s_code else None) for t_id, s_code in team_suits}

    symbols = (await db.execute(select(JHSymbol))).scalars().all()
    symbols_by_suit: dict[str, list[JHSymbol]] = {}
    for s in symbols:
        if s.suit:
            symbols_by_suit.setdefault(s.suit.upper(), []).append(s)
    all_symbol_ids = [s.symbol_id for s in symbols]

    secure_random = random.SystemRandom()
    for round_row in jh_rounds:
        for team_id in team_ids:
            suit_code = team_suit_map.get(team_id)
            avail = symbols_by_suit.get(suit_code, []) if suit_code else []
            if avail:
                chosen = secure_random.choice(avail)
                chosen_symbol_id = chosen.symbol_id
            else:
                chosen_symbol_id = secure_random.choice(all_symbol_ids)
            db.add(JackHeartAssignment(round_id=round_row.round_id, team_id=team_id, symbol_id=chosen_symbol_id))
    await db.flush()


# ---------------------------------------------------------------------------
# §1 — Round-scoped, cross-room control layer
#
# Everything above this line is modeled per room: one call = one room. The
# functions below fan a single admin action out to every room in an event
# Round whose configured lineup includes the given game_code, so "start
# MindMaze everywhere" is one call instead of a client-side loop with no
# atomicity or partial-failure reporting.
#
# Naming note (round_id ambiguity, flagged in the audit): `round_id` here
# always means the *event* Round (app.models.round.Round — the thing that
# owns 10 Rooms). It is NOT the same id as a MindmazeRound/KingDiamondRound/
# JackHeartRound row's `round_id` (a single numbered round *within* one
# room's session), which this module calls a "game-round" in comments to
# keep the two apart.
#
# Design choice vs. the audit's SAVEPOINT suggestion: each room here gets
# its own dedicated AsyncSession (via async_session_maker(), the same
# pattern app/workers/jobs.py already uses for background jobs) rather than
# a db.begin_nested() SAVEPOINT on the caller's session. The single-room
# functions above (start_session, pause_session, ...) each call db.commit()
# internally; running them under a SAVEPOINT would mean their commit() only
# flushed to the savepoint and was lost when an outer rollback fired.
#
# Everything above this line is modeled per room: one call = one room. The
# functions below fan a single admin action out to every room in an event
# Round whose configured lineup includes the given game_code, so "start
# MindMaze everywhere" is one call instead of a client-side loop with no
# atomicity or partial-failure reporting.
#
# Naming note (round_id ambiguity, flagged in the audit): `round_id` here
# always means the *event* Round (app.models.round.Round — the thing that
# owns 10 Rooms). It is NOT the same id as a MindmazeRound/KingDiamondRound/
# JackHeartRound row's `round_id` (a single numbered round *within* one
# room's session), which this module calls a "game-round" in comments to
# keep the two apart.
#
# Design choice vs. the audit's SAVEPOINT suggestion: each room here gets
# its own dedicated AsyncSession (via async_session_maker(), the same
# pattern app/workers/jobs.py already uses for background jobs) rather than
# a db.begin_nested() SAVEPOINT on the caller's session. The single-room
# functions above (start_session, pause_session, ...) each call db.commit()
# internally; running them under a SAVEPOINT would mean their commit() only
# releases the SAVEPOINT rather than truly committing, which is easy to get
# subtly wrong. A separate session per room gives the same "one room's
# failure can't touch another room's already-committed work" guarantee with
# no special-casing of the reused single-room functions.
# ---------------------------------------------------------------------------


async def _rooms_with_game_in_round(
    db: AsyncSession, *, round_id: uuid.UUID, game_code: str
) -> tuple[list[tuple[uuid.UUID, str]], Game]:
    """Every Room in this event Round whose round_games lineup includes
    game_code, in room_number order. Raises NotFoundError if the game_code
    is unknown or no room in the round currently has it in its lineup."""
    game = (await db.execute(select(Game).where(Game.code == game_code))).scalar_one_or_none()
    if game is None:
        raise NotFoundError(f"Unknown game_code '{game_code}'")

    rows = (
        await db.execute(
            select(Room.room_id, Room.room_code)
            .join(RoundGames, RoundGames.round_id == Room.round_id)
            .where(Room.round_id == round_id, RoundGames.game_id == game.game_id)
            .order_by(Room.room_number)
        )
    ).all()
    if not rows:
        raise NotFoundError(f"No rooms in this round have '{game_code}' in their lineup")
    return [(r.room_id, r.room_code) for r in rows], game


async def _session_for_room_game(
    db: AsyncSession, *, room_id: uuid.UUID, game_id: uuid.UUID
) -> GameSession | None:
    return (
        await db.execute(
            select(GameSession).where(GameSession.room_id == room_id, GameSession.game_id == game_id)
        )
    ).scalar_one_or_none()


async def start_session_for_round(
    db: AsyncSession,
    *,
    round_id: uuid.UUID,
    game_code: str,
    duration_minutes: int,
    num_rounds: int,
) -> list[dict]:
    """Fans start_session() out to every room in the round with game_code in
    its lineup."""
    rooms, _game = await _rooms_with_game_in_round(db, round_id=round_id, game_code=game_code)

    results = []
    for room_id, room_code in rooms:
        async with async_session_maker() as room_db:
            try:
                session, rounds = await start_session(
                    room_db,
                    room_id=room_id,
                    game_code=game_code,
                    duration_minutes=duration_minutes,
                    num_rounds=num_rounds,
                )
                results.append(
                    {"room_id": room_id, "room_code": room_code, "ok": True, "session": session, "rounds": rounds}
                )
            except (ConflictError, NotFoundError) as exc:
                results.append({"room_id": room_id, "room_code": room_code, "ok": False, "reason": str(exc)})
    return results


async def _fan_out_session_action(
    db: AsyncSession, *, round_id: uuid.UUID, game_code: str, action
) -> list[dict]:
    rooms, game = await _rooms_with_game_in_round(db, round_id=round_id, game_code=game_code)

    results = []
    for room_id, room_code in rooms:
        async with async_session_maker() as room_db:
            try:
                session = await _session_for_room_game(room_db, room_id=room_id, game_id=game.game_id)
                if session is None:
                    raise NotFoundError(f"No {game_code} session has been started in this room yet")
                out_session, rounds = await action(room_db, session.session_id)
                results.append(
                    {
                        "room_id": room_id,
                        "room_code": room_code,
                        "ok": True,
                        "session": out_session,
                        "rounds": rounds,
                    }
                )
            except (ConflictError, NotFoundError) as exc:
                results.append({"room_id": room_id, "room_code": room_code, "ok": False, "reason": str(exc)})
    return results


async def start_next_subround(
    db: AsyncSession, *, session_id: uuid.UUID
) -> tuple[GameSession, list]:
    session, game, round_model = await _get_session_and_rounds(db, session_id)
    if session.status != SessionStatus.IN_PROGRESS:
        raise ConflictError(f"Session for {game.code} is {session.status.value}, not IN_PROGRESS")

    rounds = (
        (
            await db.execute(
                select(round_model)
                .where(round_model.session_id == session_id)
                .order_by(round_model.round_number)
            )
        )
        .scalars()
        .all()
    )
    if not rounds:
        raise NotFoundError("No rounds found for this session")

    next_round = next((r for r in rounds if r.start_time is None), None)
    if next_round is None:
        raise ConflictError("All sub-rounds for this session have already been started")

    now = datetime.now(timezone.utc)
    start_time = now + SUBROUND_START_LEAD

    if game.code == "MINDMAZE":
        play = timedelta(seconds=settings.mindmaze_round_seconds)
    elif game.code == "ACE_SPADE":
        play = timedelta(seconds=settings.ace_spade_round_seconds)
    elif game.code == "KING_DIAMOND":
        # Aug 2026: fixed 45s auto-submit pacing — see
        # settings.king_diamond_round_seconds.
        play = timedelta(seconds=settings.king_diamond_round_seconds)
    else:
        r1 = rounds[0]
        if r1.start_time and r1.deadline:
            play = r1.deadline - r1.start_time
        else:
            play = timedelta(minutes=1)

    next_round.start_time = start_time
    next_round.deadline = start_time + play

    await db.commit()
    for r in rounds:
        await db.refresh(r)
    await db.refresh(session)

    # Validate that all active rounds have deadlines set
    from app.workers.scheduler import validate_active_deadlines
    validate_active_deadlines(rounds)

    from app.workers.scheduler import schedule_round_close
    schedule_round_close(game.code, next_round.round_id, next_round.deadline)

    return session, rounds


async def start_next_subround_for_round(
    db: AsyncSession, *, round_id: uuid.UUID, game_code: str
) -> list[dict]:
    return await _fan_out_session_action(
        db, round_id=round_id, game_code=game_code, action=lambda d, sid: start_next_subround(d, session_id=sid)
    )


async def start_subround_by_number(
    db: AsyncSession, *, session_id: uuid.UUID, subround_number: int
) -> tuple[GameSession, list]:
    session, game, round_model = await _get_session_and_rounds(db, session_id)
    if session.status != SessionStatus.IN_PROGRESS:
        raise ConflictError(f"Session for {game.code} is {session.status.value}, not IN_PROGRESS")

    rounds = (
        (
            await db.execute(
                select(round_model)
                .where(round_model.session_id == session_id)
                .order_by(round_model.round_number)
            )
        )
        .scalars()
        .all()
    )
    target_round = next((r for r in rounds if r.round_number == subround_number), None)
    if target_round is None:
        raise NotFoundError(f"Sub-round {subround_number} not found for this session")

    now = datetime.now(timezone.utc)
    start_time = now + SUBROUND_START_LEAD

    if game.code == "MINDMAZE":
        play = timedelta(seconds=settings.mindmaze_round_seconds)
    elif game.code == "ACE_SPADE":
        play = timedelta(seconds=settings.ace_spade_round_seconds)
    elif game.code == "KING_DIAMOND":
        # Aug 2026: fixed 45s auto-submit pacing — see
        # settings.king_diamond_round_seconds.
        play = timedelta(seconds=settings.king_diamond_round_seconds)
    else:
        r1 = rounds[0]
        if r1.start_time and r1.deadline:
            play = r1.deadline - r1.start_time
        else:
            play = timedelta(minutes=1)

    target_round.start_time = start_time
    target_round.deadline = start_time + play

    await db.commit()
    for r in rounds:
        await db.refresh(r)
    await db.refresh(session)

    from app.workers.scheduler import schedule_round_close
    schedule_round_close(game.code, target_round.round_id, target_round.deadline)

    return session, rounds


async def start_subround_by_number_for_round(
    db: AsyncSession, *, round_id: uuid.UUID, game_code: str, subround_number: int
) -> list[dict]:
    return await _fan_out_session_action(
        db,
        round_id=round_id,
        game_code=game_code,
        action=lambda d, sid: start_subround_by_number(d, session_id=sid, subround_number=subround_number),
    )


async def restart_subround_by_number(
    db: AsyncSession, *, session_id: uuid.UUID, subround_number: int
) -> tuple[GameSession, list]:
    session, game, round_model = await _get_session_and_rounds(db, session_id)

    rounds = (
        (
            await db.execute(
                select(round_model)
                .where(round_model.session_id == session_id)
                .order_by(round_model.round_number)
            )
        )
        .scalars()
        .all()
    )
    target_round = next((r for r in rounds if r.round_number == subround_number), None)
    if target_round is None:
        raise NotFoundError(f"Sub-round {subround_number} not found for this session")

    from app.workers.scheduler import cancel_round_close
    cancel_round_close(game.code, target_round.round_id)

    if game.code == "MINDMAZE":
        from app.models.mindmaze import MindmazeResult
        await db.execute(delete(MindmazeResult).where(MindmazeResult.round_id == target_round.round_id))
    elif game.code == "ACE_SPADE":
        from app.models.ace_spade import AceSpadeResult
        await db.execute(delete(AceSpadeResult).where(AceSpadeResult.round_id == target_round.round_id))
    elif game.code == "JACK_HEART":
        from app.models.jack_heart import JackHeartAnswer, JackHeartAssignment, JHSymbol
        from app.models.selection import Round1Selection

        # 1. Delete previous answers for this restarted round so points recalculate cleanly
        await db.execute(delete(JackHeartAnswer).where(JackHeartAnswer.round_id == target_round.round_id))
        
        # 2. Delete previous symbol assignments for this round
        await db.execute(delete(JackHeartAssignment).where(JackHeartAssignment.round_id == target_round.round_id))
        await db.flush()

        # 3. Re-assign fresh random cards from each team's respective suit
        team_ids = (
            (await db.execute(select(Round1Selection.team_id).where(Round1Selection.room_id == session.room_id)))
            .scalars()
            .all()
        )
        if team_ids:
            team_suits = (
                await db.execute(
                    select(Round1Selection.team_id, Suit.code)
                    .join(Suit, Suit.suit_id == Round1Selection.suit_id)
                    .where(Round1Selection.team_id.in_(team_ids))
                )
            ).all()
            team_suit_map = {t_id: (s_code.upper() if s_code else None) for t_id, s_code in team_suits}

            symbols = (await db.execute(select(JHSymbol))).scalars().all()
            symbols_by_suit: dict[str, list[JHSymbol]] = {}
            for s in symbols:
                if s.suit:
                    symbols_by_suit.setdefault(s.suit.upper(), []).append(s)
            all_symbol_ids = [s.symbol_id for s in symbols]
            secure_random = random.SystemRandom()
            for team_id in team_ids:
                suit_code = team_suit_map.get(team_id)
                avail = symbols_by_suit.get(suit_code, []) if suit_code else []
                if avail:
                    chosen = secure_random.choice(avail)
                    chosen_symbol_id = chosen.symbol_id
                else:
                    chosen_symbol_id = secure_random.choice(all_symbol_ids)
                db.add(JackHeartAssignment(round_id=target_round.round_id, team_id=team_id, symbol_id=chosen_symbol_id))
            await db.flush()
    elif game.code == "KING_DIAMOND":
        from app.models.king_diamond import KingDiamondSubmission
        target_round.winner_submission_id = None
        target_round.average_value = None
        target_round.target_value = None
        target_round.is_closed = False
        await db.flush()
        await db.execute(delete(KingDiamondSubmission).where(KingDiamondSubmission.round_id == target_round.round_id))

    now = datetime.now(timezone.utc)
    start_time = now + SUBROUND_START_LEAD

    if game.code == "MINDMAZE":
        play = timedelta(seconds=settings.mindmaze_round_seconds)
    elif game.code == "ACE_SPADE":
        play = timedelta(seconds=settings.ace_spade_round_seconds)
    elif game.code == "KING_DIAMOND":
        play = timedelta(seconds=settings.king_diamond_round_seconds)
    else:
        r1 = rounds[0]
        if r1.start_time and r1.deadline:
            play = r1.deadline - r1.start_time
        else:
            play = timedelta(minutes=1)

    target_round.start_time = start_time
    target_round.deadline = start_time + play
    if hasattr(target_round, "is_closed"):
        target_round.is_closed = False

    if session.status == SessionStatus.COMPLETED:
        session.status = SessionStatus.IN_PROGRESS
    session.is_published = False
    # Recompute live GameScore for each team from remaining valid subrounds
    from app.models.game import GameScore
    from app.models.round import Room, RoomStatus
    from app.models.selection import Round1Selection

    team_ids = (
        (await db.execute(select(Round1Selection.team_id).where(Round1Selection.room_id == session.room_id)))
        .scalars()
        .all()
    )

    if game.code == "MINDMAZE":
        from app.models.mindmaze import MindmazeResult, MindmazeRound
        res = (await db.execute(
            select(
                MindmazeResult.team_id,
                func.coalesce(func.sum(MindmazeResult.round_score), 0.0)
            )
            .join(MindmazeRound, MindmazeRound.round_id == MindmazeResult.round_id)
            .where(MindmazeRound.session_id == session_id)
            .group_by(MindmazeResult.team_id)
        )).all()
        totals = {t_id: float(tot) for t_id, tot in res}
        for tid in team_ids:
            gs = (await db.execute(select(GameScore).where(GameScore.session_id == session_id, GameScore.team_id == tid))).scalar_one_or_none()
            if gs:
                gs.score = totals.get(tid, 0.0)
                gs.completed = False
            else:
                db.add(GameScore(session_id=session_id, team_id=tid, score=totals.get(tid, 0.0), completed=False))

    elif game.code == "ACE_SPADE":
        from app.models.ace_spade import AceSpadeResult, AceSpadeRound
        res = (await db.execute(
            select(
                AceSpadeResult.team_id,
                func.coalesce(func.sum(AceSpadeResult.round_score), 0.0)
            )
            .join(AceSpadeRound, AceSpadeRound.round_id == AceSpadeResult.round_id)
            .where(AceSpadeRound.session_id == session_id)
            .group_by(AceSpadeResult.team_id)
        )).all()
        totals = {t_id: float(tot) for t_id, tot in res}
        for tid in team_ids:
            gs = (await db.execute(select(GameScore).where(GameScore.session_id == session_id, GameScore.team_id == tid))).scalar_one_or_none()
            if gs:
                gs.score = totals.get(tid, 0.0)
                gs.completed = False
            else:
                db.add(GameScore(session_id=session_id, team_id=tid, score=totals.get(tid, 0.0), completed=False))

    elif game.code == "JACK_HEART":
        from app.models.jack_heart import JackHeartAnswer, JackHeartRound
        res = (await db.execute(
            select(
                JackHeartAnswer.team_id,
                func.coalesce(func.sum(JackHeartAnswer.round_score), 0.0)
            )
            .join(JackHeartRound, JackHeartRound.round_id == JackHeartAnswer.round_id)
            .where(JackHeartRound.session_id == session_id)
            .group_by(JackHeartAnswer.team_id)
        )).all()
        totals = {t_id: float(tot) for t_id, tot in res}
        for tid in team_ids:
            gs = (await db.execute(select(GameScore).where(GameScore.session_id == session_id, GameScore.team_id == tid))).scalar_one_or_none()
            if gs:
                gs.score = totals.get(tid, 0.0)
                gs.completed = False
            else:
                db.add(GameScore(session_id=session_id, team_id=tid, score=totals.get(tid, 0.0), completed=False))

    elif game.code == "KING_DIAMOND":
        from app.models.king_diamond import KingDiamondRound, KingDiamondSubmission
        total_rounds_cnt = (
            await db.execute(
                select(func.count(KingDiamondRound.round_id)).where(KingDiamondRound.session_id == session_id)
            )
        ).scalar() or 5
        total_base = float(total_rounds_cnt * settings.king_diamond_base_points)

        closed_rounds = (await db.execute(select(KingDiamondRound).where(KingDiamondRound.session_id == session_id, KingDiamondRound.is_closed == True))).scalars().all()
        closed_rids = [r.round_id for r in closed_rounds]
        penalties = {}
        if closed_rids:
            pen_res = (await db.execute(
                select(KingDiamondSubmission.team_id, func.coalesce(func.sum(KingDiamondSubmission.round_score), 0.0))
                .where(KingDiamondSubmission.round_id.in_(closed_rids))
                .group_by(KingDiamondSubmission.team_id)
            )).all()
            penalties = {row[0]: float(row[1]) for row in pen_res}
        for tid in team_ids:
            tot = max(0.0, total_base - penalties.get(tid, 0.0))
            gs = (await db.execute(select(GameScore).where(GameScore.session_id == session_id, GameScore.team_id == tid))).scalar_one_or_none()
            if gs:
                gs.score = float(tot)
                gs.completed = False
            else:
                db.add(GameScore(session_id=session_id, team_id=tid, score=float(tot), completed=False))

    room = await db.get(Room, session.room_id)
    if room is not None and room.status == RoomStatus.COMPLETED:
        room.status = RoomStatus.ACTIVE

    await db.flush()
    try:
        await db.execute(
            text("SELECT fn_compute_room_results(:room_id)"),
            {"room_id": str(session.room_id)},
        )
    except Exception:
        pass

    await db.commit()
    for r in rounds:
        await db.refresh(r)
    await db.refresh(session)

    from app.workers.scheduler import schedule_round_close
    schedule_round_close(game.code, target_round.round_id, target_round.deadline)

    from app.workers.jobs import _publish
    await _publish(f"room:{session.room_id}:sessions")
    await _publish(f"room:{session.room_id}:leaderboard")

    return session, rounds


async def restart_subround_by_number_for_round(
    db: AsyncSession, *, round_id: uuid.UUID, game_code: str, subround_number: int
) -> list[dict]:
    return await _fan_out_session_action(
        db,
        round_id=round_id,
        game_code=game_code,
        action=lambda d, sid: restart_subround_by_number(d, session_id=sid, subround_number=subround_number),
    )


async def pause_subround_by_number(
    db: AsyncSession, *, session_id: uuid.UUID, subround_number: int
) -> tuple[GameSession, list]:
    session, game, round_model = await _get_session_and_rounds(db, session_id)

    rounds = (
        (
            await db.execute(
                select(round_model)
                .where(round_model.session_id == session_id)
                .order_by(round_model.round_number)
            )
        )
        .scalars()
        .all()
    )
    target_round = next((r for r in rounds if r.round_number == subround_number), None)
    if target_round is None:
        raise NotFoundError(f"Sub-round {subround_number} not found for this session")

    from app.workers.scheduler import cancel_round_close
    cancel_round_close(game.code, target_round.round_id)

    if session.status == SessionStatus.IN_PROGRESS:
        session.status = SessionStatus.PAUSED
        session.paused_at = datetime.now(timezone.utc)

    await db.commit()
    for r in rounds:
        await db.refresh(r)
    await db.refresh(session)

    return session, rounds


async def pause_subround_by_number_for_round(
    db: AsyncSession, *, round_id: uuid.UUID, game_code: str, subround_number: int
) -> list[dict]:
    return await _fan_out_session_action(
        db,
        round_id=round_id,
        game_code=game_code,
        action=lambda d, sid: pause_subround_by_number(d, session_id=sid, subround_number=subround_number),
    )




async def pause_sessions_for_round(db: AsyncSession, *, round_id: uuid.UUID, game_code: str) -> list[dict]:


    return await _fan_out_session_action(
        db, round_id=round_id, game_code=game_code, action=lambda d, sid: pause_session(d, session_id=sid)
    )


async def resume_sessions_for_round(db: AsyncSession, *, round_id: uuid.UUID, game_code: str) -> list[dict]:
    return await _fan_out_session_action(
        db, round_id=round_id, game_code=game_code, action=lambda d, sid: resume_session(d, session_id=sid)
    )


async def restart_sessions_for_round(db: AsyncSession, *, round_id: uuid.UUID, game_code: str) -> list[dict]:
    return await _fan_out_session_action(
        db, round_id=round_id, game_code=game_code, action=lambda d, sid: restart_session(d, session_id=sid)
    )


async def force_complete_sessions_for_round(
    db: AsyncSession, *, round_id: uuid.UUID, game_code: str
) -> list[dict]:
    from app.workers import jobs

    rooms, game = await _rooms_with_game_in_round(db, round_id=round_id, game_code=game_code)

    results = []
    for room_id, room_code in rooms:
        async with async_session_maker() as room_db:
            try:
                session = await _session_for_room_game(room_db, room_id=room_id, game_id=game.game_id)
                if session is None:
                    raise NotFoundError(f"No {game_code} session has been started in this room yet")
                if session.status == SessionStatus.PAUSED:
                    raise ConflictError("Resume the session before force-completing it.")
                await jobs._maybe_close_session(session.session_id, force=True)
                results.append(
                    {"room_id": room_id, "room_code": room_code, "ok": True, "session_id": session.session_id}
                )
            except (ConflictError, NotFoundError) as exc:
                results.append({"room_id": room_id, "room_code": room_code, "ok": False, "reason": str(exc)})
    return results


async def show_instructions_for_round(
    db: AsyncSession, *, round_id: uuid.UUID, game_code: str
) -> list[dict]:
    rooms, game = await _rooms_with_game_in_round(db, round_id=round_id, game_code=game_code)
    results = []
    now_plus_5 = datetime.now(timezone.utc) + timedelta(minutes=5)
    for room_id, room_code in rooms:
        async with async_session_maker() as room_db:
            try:
                session = await _session_for_room_game(room_db, room_id=room_id, game_id=game.game_id)
                if session is None:
                    session = GameSession(round_id=round_id, room_id=room_id, game_id=game.game_id, status=SessionStatus.NOT_STARTED)
                    room_db.add(session)
                session.instruction_until = now_plus_5
                await room_db.commit()
                results.append({"room_id": room_id, "room_code": room_code, "ok": True, "session_id": session.session_id})
            except (ConflictError, NotFoundError) as exc:
                results.append({"room_id": room_id, "room_code": room_code, "ok": False, "reason": str(exc)})
    return results


async def list_game_round_ids_for_round(
    db: AsyncSession, *, round_id: uuid.UUID, game_code: str
) -> list[uuid.UUID]:
    round_model = _ROUND_MODEL_BY_GAME_CODE.get(game_code)
    if round_model is None:
        raise NotFoundError(f"Unknown game_code '{game_code}'")
    game = (await db.execute(select(Game).where(Game.code == game_code))).scalar_one_or_none()
    if game is None:
        raise NotFoundError(f"Unknown game_code '{game_code}'")

    session_ids = (
        await db.execute(
            select(GameSession.session_id).where(
                GameSession.round_id == round_id, GameSession.game_id == game.game_id
            )
        )
    ).scalars().all()
    if not session_ids:
        return []

    return (
        (await db.execute(select(round_model.round_id).where(round_model.session_id.in_(session_ids))))
        .scalars()
        .all()
    )
