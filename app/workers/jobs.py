"""
Deadline-driven jobs, matching the roll-up chain from the design doc §7:

  close_*_round  ->  (all rounds of a session closed?)  ->  close_session
  close_session  ->  (all sessions of a room COMPLETED?) ->  close_room

Every job is written to be idempotent (safe to run twice) so a scheduler
retry or overlap can't double-process a round.
"""

import logging
import uuid
from datetime import datetime, timezone

import redis.asyncio as redis
from sqlalchemy import func, select

from app.core.config import settings
from app.core.exceptions import ConflictError
from app.db.session import async_session_maker
from app.models.ace_spade import AceSpadeResult, AceSpadeRound
from app.models.game import Game, GameScore, GameSession, RoundGames, SessionStatus
from app.models.jack_heart import JackHeartAnswer, JackHeartRound
from app.models.king_diamond import KingDiamondRound
from app.models.mindmaze import MindmazeResult, MindmazeRound
from app.models.round import Room, RoomStatus
from app.models.selection import Round1Selection
from app.services import king_diamond_service, results_service

logger = logging.getLogger("round1.jobs")


async def _publish(channel: str) -> None:
    try:
        redis_client = redis.from_url(settings.redis_url)
        await redis_client.publish(channel, "updated")
        await redis_client.close()
    except Exception:
        logger.exception("Failed to publish to redis channel %s", channel)


async def close_mindmaze_round(round_id: uuid.UUID) -> None:
    async with async_session_maker() as db:
        round_obj = await db.get(MindmazeRound, round_id)
        if round_obj is None:
            logger.warning("close_mindmaze_round: round %s not found", round_id)
            return

        session = await db.get(GameSession, round_obj.session_id)
        if session is None:
            logger.warning("close_mindmaze_round: session for round %s not found", round_id)
            return
        team_ids = (
            (
                await db.execute(
                    select(Round1Selection.team_id).where(Round1Selection.room_id == session.room_id)
                )
            )
            .scalars()
            .all()
        )
        submitted_team_ids = set(
            (
                await db.execute(
                    select(MindmazeResult.team_id).where(MindmazeResult.round_id == round_id)
                )
            )
            .scalars()
            .all()
        )
        missing = [t for t in team_ids if t not in submitted_team_ids]
        for team_id in missing:
            db.add(
                MindmazeResult(
                    round_id=round_id,
                    team_id=team_id,
                    moves=0,
                    mistakes=0,
                    correct_tiles=0,
                    round_score=0,
                )
            )
        await db.flush()

        # Update live GameScore for each team in this session
        res = (
            await db.execute(
                select(
                    MindmazeResult.team_id,
                    func.coalesce(func.sum(MindmazeResult.round_score), 0.0),
                )
                .join(MindmazeRound, MindmazeRound.round_id == MindmazeResult.round_id)
                .where(MindmazeRound.session_id == session.session_id)
                .group_by(MindmazeResult.team_id)
            )
        ).all()
        totals = {t_id: float(tot) for t_id, tot in res}
        for tid in team_ids:
            gs = (
                await db.execute(
                    select(GameScore).where(
                        GameScore.session_id == session.session_id, GameScore.team_id == tid
                    )
                )
            ).scalar_one_or_none()
            if gs:
                gs.score = totals.get(tid, 0.0)
            else:
                db.add(
                    GameScore(
                        session_id=session.session_id,
                        team_id=tid,
                        score=totals.get(tid, 0.0),
                        completed=(session.status == SessionStatus.COMPLETED),
                    )
                )

        await db.commit()

        await _maybe_close_session(round_obj.session_id)
        await _publish(f"room:{session.room_id}:sessions")
        await _publish(f"room:{session.room_id}:leaderboard")
        await _publish("leaderboard:overall")


async def close_ace_spade_round(round_id: uuid.UUID) -> None:
    async with async_session_maker() as db:
        round_obj = await db.get(AceSpadeRound, round_id)
        if round_obj is None:
            logger.warning("close_ace_spade_round: round %s not found", round_id)
            return

        session = await db.get(GameSession, round_obj.session_id)
        if session is None:
            logger.warning("close_ace_spade_round: session for round %s not found", round_id)
            return
        team_ids = (
            (
                await db.execute(
                    select(Round1Selection.team_id).where(Round1Selection.room_id == session.room_id)
                )
            )
            .scalars()
            .all()
        )
        submitted_team_ids = set(
            (
                await db.execute(
                    select(AceSpadeResult.team_id).where(AceSpadeResult.round_id == round_id)
                )
            )
            .scalars()
            .all()
        )
        missing = [t for t in team_ids if t not in submitted_team_ids]
        for team_id in missing:
            db.add(
                AceSpadeResult(
                    round_id=round_id,
                    team_id=team_id,
                    moves=0,
                    wrong_picks=0,
                    correct_picks=0,
                    round_score=0,
                )
            )
        await db.flush()

        # Update live GameScore for each team in this session
        res = (
            await db.execute(
                select(
                    AceSpadeResult.team_id,
                    func.coalesce(func.sum(AceSpadeResult.round_score), 0.0),
                )
                .join(AceSpadeRound, AceSpadeRound.round_id == AceSpadeResult.round_id)
                .where(AceSpadeRound.session_id == session.session_id)
                .group_by(AceSpadeResult.team_id)
            )
        ).all()
        totals = {t_id: float(tot) for t_id, tot in res}
        for tid in team_ids:
            gs = (
                await db.execute(
                    select(GameScore).where(
                        GameScore.session_id == session.session_id, GameScore.team_id == tid
                    )
                )
            ).scalar_one_or_none()
            if gs:
                gs.score = totals.get(tid, 0.0)
            else:
                db.add(
                    GameScore(
                        session_id=session.session_id,
                        team_id=tid,
                        score=totals.get(tid, 0.0),
                        completed=(session.status == SessionStatus.COMPLETED),
                    )
                )

        await db.commit()

        await _maybe_close_session(round_obj.session_id)
        await _publish(f"room:{session.room_id}:sessions")
        await _publish(f"room:{session.room_id}:leaderboard")
        await _publish("leaderboard:overall")


async def close_king_diamond_round(round_id: uuid.UUID) -> None:
    async with async_session_maker() as db:
        round_obj = await db.get(KingDiamondRound, round_id)
        if round_obj is None:
            logger.warning("close_king_diamond_round: round %s not found", round_id)
            return
        if round_obj.is_closed:
            # Idempotent: already processed by an earlier run.
            await _maybe_close_session(round_obj.session_id)
            return

        await king_diamond_service.close_round(db, round_id=round_id)
        await _maybe_close_session(round_obj.session_id)
        session = await db.get(GameSession, round_obj.session_id)
        if session:
            await _publish(f"room:{session.room_id}:sessions")
            await _publish(f"room:{session.room_id}:leaderboard")
            await _publish("leaderboard:overall")


async def close_jack_heart_round(round_id: uuid.UUID) -> None:
    async with async_session_maker() as db:
        round_obj = await db.get(JackHeartRound, round_id)
        if round_obj is None:
            logger.warning("close_jack_heart_round: round %s not found", round_id)
            return

        session = await db.get(GameSession, round_obj.session_id)
        if session is None:
            logger.warning("close_jack_heart_round: session for round %s not found", round_id)
            return
        team_ids = (
            (
                await db.execute(
                    select(Round1Selection.team_id).where(Round1Selection.room_id == session.room_id)
                )
            )
            .scalars()
            .all()
        )
        submitted_team_ids = set(
            (
                await db.execute(
                    select(JackHeartAnswer.team_id).where(JackHeartAnswer.round_id == round_id)
                )
            )
            .scalars()
            .all()
        )
        # Correct answers already scored on submit could be handled in the
        # submit endpoint's service layer with a fixed points value; here we
        # just make sure every team has a row (score 0) so the round-score
        # roll-up into game_scores has something to sum for every team.
        missing = [t for t in team_ids if t not in submitted_team_ids]
        for team_id in missing:
            from app.models.jack_heart import JackHeartAssignment

            assignment = (
                await db.execute(
                    select(JackHeartAssignment).where(
                        JackHeartAssignment.round_id == round_id,
                        JackHeartAssignment.team_id == team_id,
                    )
                )
            ).scalar_one_or_none()
            if assignment is None:
                logger.warning(
                    "close_jack_heart_round: team %s has no JackHeartAssignment for round %s "
                    "(likely moved into the room after symbol assignment ran) — no answer row created",
                    team_id,
                    round_id,
                )
                continue
            from app.models.jack_heart import JHSymbol

            # Pick any symbol other than the team's own so a no-submit
            # never accidentally scores as "correct".
            wrong_symbol_id = (
                await db.execute(
                    select(JHSymbol.symbol_id).where(JHSymbol.symbol_id != assignment.symbol_id).limit(1)
                )
            ).scalar_one()
            db.add(
                JackHeartAnswer(
                    round_id=round_id,
                    team_id=team_id,
                    submitted_symbol_id=wrong_symbol_id,
                    actual_symbol_id=assignment.symbol_id,  # overwritten identically by trigger anyway
                    round_score=0,
                )
            )
        await db.flush()

        # Update live GameScore for each team in this session
        res = (
            await db.execute(
                select(
                    JackHeartAnswer.team_id,
                    func.coalesce(func.sum(JackHeartAnswer.round_score), 0.0),
                )
                .join(JackHeartRound, JackHeartRound.round_id == JackHeartAnswer.round_id)
                .where(JackHeartRound.session_id == session.session_id)
                .group_by(JackHeartAnswer.team_id)
            )
        ).all()
        totals = {t_id: float(tot) for t_id, tot in res}
        for tid in team_ids:
            gs = (
                await db.execute(
                    select(GameScore).where(
                        GameScore.session_id == session.session_id, GameScore.team_id == tid
                    )
                )
            ).scalar_one_or_none()
            if gs:
                gs.score = totals.get(tid, 0.0)
            else:
                db.add(
                    GameScore(
                        session_id=session.session_id,
                        team_id=tid,
                        score=totals.get(tid, 0.0),
                        completed=(session.status == SessionStatus.COMPLETED),
                    )
                )

        await db.commit()

        await _maybe_close_session(round_obj.session_id)
        await _publish(f"room:{session.room_id}:sessions")
        await _publish(f"room:{session.room_id}:leaderboard")
        await _publish("leaderboard:overall")


async def _maybe_close_session(session_id: uuid.UUID, *, force: bool = False) -> None:
    """Checks whether every round of this session is past its deadline; if
    so, rolls round_score up into game_scores and marks the session
    COMPLETED, then checks whether the room is done too.

    force=True skips the "has every round reached its deadline yet" check —
    used by the admin force-complete endpoint (Audit Issue 3's manual
    escape hatch) when the scheduled close job was lost."""
    async with async_session_maker() as db:
        session = await db.get(GameSession, session_id)
        if session is None or session.status in (SessionStatus.COMPLETED, SessionStatus.PAUSED):
            return

        game = await db.get(Game, session.game_id)
        now = datetime.now(timezone.utc)

        if game.code == "MINDMAZE":
            rounds = (
                (await db.execute(select(MindmazeRound).where(MindmazeRound.session_id == session_id)))
                .scalars()
                .all()
            )
            score_rows = (
                await db.execute(select(MindmazeResult).where(MindmazeResult.round_id.in_([r.round_id for r in rounds])))
            ).scalars().all()
        elif game.code == "ACE_SPADE":
            rounds = (
                (await db.execute(select(AceSpadeRound).where(AceSpadeRound.session_id == session_id)))
                .scalars()
                .all()
            )
            score_rows = (
                await db.execute(select(AceSpadeResult).where(AceSpadeResult.round_id.in_([r.round_id for r in rounds])))
            ).scalars().all()
        elif game.code == "KING_DIAMOND":
            rounds = (
                (await db.execute(select(KingDiamondRound).where(KingDiamondRound.session_id == session_id)))
                .scalars()
                .all()
            )
            if not all(r.is_closed for r in rounds):
                # Even with force=True we don't fabricate KD scores here —
                # close each KD round first via
                # POST /admin/king-diamond/rounds/{round_id}/force-close,
                # which computes averages/ranks/round_score properly.
                if force:
                    # Surface this to the admin instead of a silent 204 —
                    # otherwise force-complete looks like it worked and the
                    # session just never becomes COMPLETED.
                    raise ConflictError(
                        "Force-close each King of Diamonds round first via "
                        "POST /admin/king-diamond/rounds/{round_id}/force-close"
                    )
                return
            from app.models.king_diamond import KingDiamondSubmission

            score_rows = (
                await db.execute(
                    select(KingDiamondSubmission).where(
                        KingDiamondSubmission.round_id.in_([r.round_id for r in rounds])
                    )
                )
            ).scalars().all()
        elif game.code == "JACK_HEART":
            rounds = (
                (await db.execute(select(JackHeartRound).where(JackHeartRound.session_id == session_id)))
                .scalars()
                .all()
            )
            score_rows = (
                await db.execute(select(JackHeartAnswer).where(JackHeartAnswer.round_id.in_([r.round_id for r in rounds])))
            ).scalars().all()
        else:
            return

        # Bug-fix batch (Aug 2026): a MindMaze/Jack-of-Hearts session's later
        # sub-rounds are created with deadline=None and only get a real
        # deadline once the admin manually starts them (see
        # session_service.start_subround_by_number). The old check here —
        # `r.deadline is not None and r.deadline > now` — treated a
        # not-yet-started sub-round (deadline=None) as if it had *already*
        # reached its deadline, because `r.deadline is not None` was False
        # for it. That made the very first sub-round's close job roll the
        # whole session up to COMPLETED, even with 4 more configured
        # sub-rounds still sitting untouched. The team app would then show
        # the final leaderboard after sub-round 1, and any further
        # "Start sub-round N" click from the admin would fail with
        # "Session is COMPLETED, not IN_PROGRESS". A sub-round now only
        # counts as "reached its deadline" once it actually HAS a deadline
        # AND that deadline has passed; still-unstarted sub-rounds correctly
        # block the session from closing.
        if not rounds or (not force and any((r.deadline is None or r.deadline > now) for r in rounds)):
            return  # not every round has reached its deadline yet

        # Audit §2.5 / §2.7: previously totals only ever got an entry for a
        # team that had at least one score_row, so a team silently skipped
        # upstream (e.g. §2.5's Jack of Hearts no-assignment case, or a King
        # of Diamonds no-submit if fn_close_king_diamond_round doesn't
        # insert a placeholder row) got no GameScore row at all for this
        # session — not even a 0 — which is indistinguishable from "hasn't
        # been rolled up yet" downstream. Seed every team from the
        # session-start roster snapshot (§2.6) at 0 first, so a team that's
        # silently missing upstream still ends up with an explicit 0
        # GameScore row like every other non-submitting team, instead of no
        # row at all. Falls back to "only teams with score_rows" for
        # sessions started before roster_team_ids existed.
        totals: dict[uuid.UUID, float] = {}
        if game.code == "KING_DIAMOND":
            total_base = float(len(rounds) * settings.king_diamond_base_points)
            if session.roster_team_ids:
                totals = {uuid.UUID(t): total_base for t in session.roster_team_ids}
            for row in score_rows:
                if row.team_id not in totals:
                    totals[row.team_id] = total_base
                totals[row.team_id] -= float(row.round_score or 0)
            for team_id in totals:
                totals[team_id] = max(0.0, totals[team_id])
        else:
            if session.roster_team_ids:
                totals = {uuid.UUID(t): 0.0 for t in session.roster_team_ids}
            for row in score_rows:
                totals[row.team_id] = totals.get(row.team_id, 0) + float(row.round_score or 0)

        for team_id, total in totals.items():
            existing = (
                await db.execute(
                    select(GameScore).where(GameScore.session_id == session_id, GameScore.team_id == team_id)
                )
            ).scalar_one_or_none()
            if existing:
                existing.score = total
                existing.completed = True
            else:
                db.add(GameScore(session_id=session_id, team_id=team_id, score=total, completed=True))

        session.status = SessionStatus.COMPLETED
        session.end_time = now
        await db.commit()

        await _maybe_close_room(session.room_id)


async def _maybe_close_room(room_id: uuid.UUID) -> None:
    """Once every session in a room's *configured* game lineup is
    COMPLETED: recompute room_results and mark the room COMPLETED.

    Audit §2.1: this used to hardcode `len(sessions) < 3`, so a round
    configured with a lineup other than exactly 3 games (via PUT
    /admin/rounds/{round_id}/games) would either never close the room (a 2
    or 1 game lineup) or close it too early relative to what was actually
    configured. Compares against round_games's actual row count instead.

    Audit §2.2 note: room_results / v_room_leaderboard / v_overall_leaderboard
    still have fixed mindmaze_score/king_diamond_score/jack_heart_score
    columns (sql/round1_schema.sql) — the schema is intentionally scoped to
    exactly these three named games; PUT /admin/rounds/{round_id}/games only
    configures *which subset* of these three runs in a round, not arbitrary
    new games (admin_service.replace_game_lineup rejects unknown codes).
    That's a narrower, tractable "configurable lineup" than the schema could
    fully support, chosen over rewriting the results pipeline to be
    game-count-agnostic. See README.md's design notes."""
    async with async_session_maker() as db:
        room = await db.get(Room, room_id)
        if room is None or room.status == RoomStatus.COMPLETED:
            return

        lineup_size = (
            await db.execute(
                select(func.count()).select_from(RoundGames).where(RoundGames.round_id == room.round_id)
            )
        ).scalar_one()
        if lineup_size == 0:
            # No lineup configured for this round yet — nothing to close.
            return

        sessions = (await db.execute(select(GameSession).where(GameSession.room_id == room_id))).scalars().all()
        if len(sessions) < lineup_size or any(s.status != SessionStatus.COMPLETED for s in sessions):
            return

        await results_service.recompute_room_results(db, room_id=room_id)

        room.status = RoomStatus.COMPLETED
        await db.commit()

        logger.info("Room %s fully closed and results computed", room_id)

    # Published after commit, outside the `async with` DB session block —
    # keeps the WS layer dumb: it never computes anything, just relays this
    # notification by re-reading the leaderboard views.
    await _publish(f"room:{room_id}:leaderboard")
    await _publish("leaderboard:overall")
