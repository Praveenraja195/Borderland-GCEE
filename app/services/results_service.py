import logging
import uuid
from datetime import datetime, timezone

import redis.asyncio as redis
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.models.ace_spade import AceSpadeResult, AceSpadeRound
from app.models.game import Game, GameScore, GameSession, SessionStatus
from app.models.jack_heart import JackHeartAnswer, JackHeartRound
from app.models.king_diamond import KingDiamondRound, KingDiamondSubmission
from app.models.mindmaze import MindmazeResult, MindmazeRound
from app.models.round import Room, RoomStatus
from app.models.selection import Round1Selection

logger = logging.getLogger("round1.results")


async def _publish(channel: str) -> None:
    try:
        redis_client = redis.from_url(settings.redis_url)
        await redis_client.publish(channel, "updated")
        await redis_client.close()
    except Exception:
        logger.exception("Failed to publish to redis channel %s", channel)


async def recompute_room_results(db: AsyncSession, *, room_id: uuid.UUID) -> None:
    """Manually aggregates all subround scores into game_scores for every game
    session in the room, re-runs fn_compute_room_results(room_id), and broadcasts
    updated leaderboards to WebSocket subscribers."""
    room = await db.get(Room, room_id)
    if room is None:
        raise NotFoundError("Room not found")

    # Get all teams in this room
    team_ids = (
        (await db.execute(select(Round1Selection.team_id).where(Round1Selection.room_id == room_id)))
        .scalars()
        .all()
    )

    # Fetch all sessions in this room
    sessions = (
        (await db.execute(select(GameSession).where(GameSession.room_id == room_id)))
        .scalars()
        .all()
    )

    for session in sessions:
        game = await db.get(Game, session.game_id)
        if game is None:
            continue

        if game.code == "MINDMAZE":
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
                score_val = totals.get(tid, 0.0)
                if gs:
                    gs.score = score_val
                else:
                    db.add(
                        GameScore(
                            session_id=session.session_id,
                            team_id=tid,
                            score=score_val,
                            completed=(session.status == SessionStatus.COMPLETED),
                        )
                    )

        elif game.code == "ACE_SPADE":
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
                score_val = totals.get(tid, 0.0)
                if gs:
                    gs.score = score_val
                else:
                    db.add(
                        GameScore(
                            session_id=session.session_id,
                            team_id=tid,
                            score=score_val,
                            completed=(session.status == SessionStatus.COMPLETED),
                        )
                    )

        elif game.code == "JACK_HEART":
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
                score_val = totals.get(tid, 0.0)
                if gs:
                    gs.score = score_val
                else:
                    db.add(
                        GameScore(
                            session_id=session.session_id,
                            team_id=tid,
                            score=score_val,
                            completed=(session.status == SessionStatus.COMPLETED),
                        )
                    )

        elif game.code == "KING_DIAMOND":
            closed_rounds = (
                (
                    await db.execute(
                        select(KingDiamondRound).where(
                            KingDiamondRound.session_id == session.session_id,
                            KingDiamondRound.is_closed == True,
                        )
                    )
                )
                .scalars()
                .all()
            )
            closed_rids = [r.round_id for r in closed_rounds]
            penalties = {}
            if closed_rids:
                pen_res = (
                    await db.execute(
                        select(
                            KingDiamondSubmission.team_id,
                            func.coalesce(func.sum(KingDiamondSubmission.round_score), 0.0),
                        )
                        .where(KingDiamondSubmission.round_id.in_(closed_rids))
                        .group_by(KingDiamondSubmission.team_id)
                    )
                ).all()
                penalties = {row[0]: float(row[1]) for row in pen_res}
            for tid in team_ids:
                tot = max(0.0, 30.0 - penalties.get(tid, 0.0))
                gs = (
                    await db.execute(
                        select(GameScore).where(
                            GameScore.session_id == session.session_id, GameScore.team_id == tid
                        )
                    )
                ).scalar_one_or_none()
                if gs:
                    gs.score = float(tot)
                else:
                    db.add(
                        GameScore(
                            session_id=session.session_id,
                            team_id=tid,
                            score=float(tot),
                            completed=(session.status == SessionStatus.COMPLETED),
                        )
                    )

    await db.flush()
    await db.execute(text("SELECT fn_compute_room_results(:room_id)"), {"room_id": str(room_id)})
    await db.commit()

    # Broadcast updates
    await _publish(f"room:{room_id}:sessions")
    await _publish(f"room:{room_id}:leaderboard")
    await _publish("leaderboard:overall")

