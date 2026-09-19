"""
WebSocket layer stays dumb: it never computes anything, just relays a DB
read (the leaderboard views) that gets triggered by a roll-up job publishing
to a Redis channel.

Fix §1.2: WebSocket endpoints now require a bearer token passed as
?token=<jwt> in the query string (browsers cannot set WS headers).
The token is validated before websocket.accept() — unauthenticated
connections are rejected with close code 4001 before any data is sent.
For the room-scoped endpoint, the connecting team's room assignment is also
verified so a team cannot subscribe to a different room's channel.
"""

import asyncio
import json
import logging
import uuid

import redis.asyncio as redis
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select, text

from app.core.config import settings
from app.core.security import decode_token
from app.db.session import async_session_maker
from app.models.selection import Round1Selection
from app.models.team import Team

logger = logging.getLogger("round1.ws")

router = APIRouter(tags=["websocket"])


async def _record_team_ws_connect(team_code: str, room_id: uuid.UUID | None = None) -> None:
    if not team_code:
        return
    try:
        r = redis.from_url(settings.redis_url)
        pipe = r.pipeline()
        pipe.incr(f"team:conn_count:{team_code}")
        pipe.expire(f"team:conn_count:{team_code}", 180)
        pipe.set(f"team:online:{team_code}", "1", ex=45)
        pipe.sadd("active_online_teams", team_code)
        if room_id:
            pipe.sadd(f"room:{room_id}:online_teams", team_code)
        await pipe.execute()
        await r.close()
    except Exception:
        logger.exception("Failed to record team connect for %s", team_code)


async def _refresh_team_ws_presence(team_code: str) -> None:
    if not team_code:
        return
    try:
        r = redis.from_url(settings.redis_url)
        pipe = r.pipeline()
        pipe.set(f"team:online:{team_code}", "1", ex=45)
        pipe.expire(f"team:conn_count:{team_code}", 180)
        await pipe.execute()
        await r.close()
    except Exception:
        pass


async def _record_team_ws_disconnect(team_code: str, room_id: uuid.UUID | None = None) -> None:
    if not team_code:
        return
    try:
        r = redis.from_url(settings.redis_url)
        remaining = await r.decr(f"team:conn_count:{team_code}")
        pipe = r.pipeline()
        if remaining <= 0:
            pipe.delete(f"team:conn_count:{team_code}")
            # Don't drop presence outright: the app also heartbeats over REST
            # every 3s, and a route change reopens the socket within
            # milliseconds. Shorten the TTL instead so a genuinely closed tab
            # disappears from the delivery board within ~15s.
            pipe.expire(f"team:online:{team_code}", 15)
            pipe.srem("active_online_teams", team_code)
            if room_id:
                pipe.srem(f"room:{room_id}:online_teams", team_code)
        else:
            pipe.set(f"team:online:{team_code}", "1", ex=45)
        await pipe.execute()
        await r.close()
    except Exception:
        logger.exception("Failed to record team disconnect for %s", team_code)


async def _resolve_team_code(payload: dict) -> str | None:
    team_code = payload.get("team_code")
    if team_code:
        return team_code
    team_id_str = payload.get("sub")
    if not team_id_str:
        return None
    try:
        t_id = uuid.UUID(team_id_str)
        async with async_session_maker() as db:
            t = await db.get(Team, t_id)
            return t.team_code if t else None
    except Exception:
        return None



async def _fetch_room_leaderboard(room_id: uuid.UUID) -> list[dict]:
    async with async_session_maker() as db:
        query = text("""
            SELECT
                r.room_id,
                r.room_code,
                t.team_code,
                t.team_name,
                st.code AS team_suit_code,
                st.symbol AS team_suit_symbol,
            CASE
                WHEN smm.is_published IS TRUE THEN
                    COALESCE(mm.score, (
                        SELECT COALESCE(SUM(mr.round_score), 0)
                        FROM mindmaze_results mr
                        JOIN mindmaze_rounds mrd ON mrd.round_id = mr.round_id
                        WHERE mrd.session_id = smm.session_id AND mr.team_id = t.team_id
                    ), 0)::FLOAT
                ELSE NULL
            END AS mindmaze_score,
            CASE
                WHEN sas.is_published IS TRUE THEN
                    COALESCE(as_.score, (
                        SELECT COALESCE(SUM(asr.round_score), 0)
                        FROM ace_spade_results asr
                        JOIN ace_spade_rounds asrd ON asrd.round_id = asr.round_id
                        WHERE asrd.session_id = sas.session_id AND asr.team_id = t.team_id
                    ), 0)::FLOAT
                ELSE NULL
            END AS ace_spade_score,
            CASE
                WHEN skd.is_published IS TRUE THEN
                    COALESCE(kd.score, GREATEST(0.0,
                        COALESCE(NULLIF((SELECT COUNT(*) FROM king_diamond_rounds WHERE session_id = skd.session_id), 0), 5) * 20.0
                        - COALESCE((
                            SELECT SUM(kds.round_score)
                            FROM king_diamond_submissions kds
                            JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
                            WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
                        ), 0.0)
                    ))::FLOAT
                ELSE NULL
            END AS king_diamond_score,
            CASE
                WHEN sjh.is_published IS TRUE THEN
                    COALESCE(jh.score, (
                        SELECT COALESCE(SUM(jha.round_score), 0)
                        FROM jack_heart_answers jha
                        JOIN jack_heart_rounds jhr ON jhr.round_id = jha.round_id
                        WHERE jhr.session_id = sjh.session_id AND jha.team_id = t.team_id
                    ), 0)::FLOAT
                ELSE NULL
            END AS jack_heart_score,
            CASE
                WHEN (smm.is_published IS TRUE OR sas.is_published IS TRUE OR skd.is_published IS TRUE OR sjh.is_published IS TRUE) THEN
                    (
                        COALESCE(CASE WHEN smm.is_published IS TRUE THEN COALESCE(mm.score, (
                            SELECT COALESCE(SUM(mr.round_score), 0)
                            FROM mindmaze_results mr
                            JOIN mindmaze_rounds mrd ON mrd.round_id = mr.round_id
                            WHERE mrd.session_id = smm.session_id AND mr.team_id = t.team_id
                        ), 0) ELSE 0 END, 0) +
                        COALESCE(CASE WHEN sas.is_published IS TRUE THEN COALESCE(as_.score, (
                            SELECT COALESCE(SUM(asr.round_score), 0)
                            FROM ace_spade_results asr
                            JOIN ace_spade_rounds asrd ON asrd.round_id = asr.round_id
                            WHERE asrd.session_id = sas.session_id AND asr.team_id = t.team_id
                        ), 0) ELSE 0 END, 0) +
                        COALESCE(CASE WHEN skd.is_published IS TRUE THEN COALESCE(kd.score, GREATEST(0.0,
                            COALESCE(NULLIF((SELECT COUNT(*) FROM king_diamond_rounds WHERE session_id = skd.session_id), 0), 5) * 20.0
                            - COALESCE((
                                SELECT SUM(kds.round_score)
                                FROM king_diamond_submissions kds
                                JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
                                WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
                            ), 0.0)
                        )) ELSE 0 END, 0) +
                        COALESCE(CASE WHEN sjh.is_published IS TRUE THEN COALESCE(jh.score, (
                            SELECT COALESCE(SUM(jha.round_score), 0)
                            FROM jack_heart_answers jha
                            JOIN jack_heart_rounds jhr ON jhr.round_id = jha.round_id
                            WHERE jhr.session_id = sjh.session_id AND jha.team_id = t.team_id
                        ), 0) ELSE 0 END, 0)
                    )::FLOAT
                ELSE NULL
            END AS total_score,
            CASE
                WHEN (rd.results_published_at IS NOT NULL) THEN
                    CASE WHEN rr.tiebreak_pending IS TRUE THEN NULL ELSE COALESCE(rr.is_qualified, FALSE) END
                ELSE NULL
            END AS is_qualified,
            CASE
                WHEN (smm.is_published IS TRUE OR sas.is_published IS TRUE OR skd.is_published IS TRUE OR sjh.is_published IS TRUE) THEN
                    RANK() OVER (
                        PARTITION BY r.room_id
                        ORDER BY (
                            COALESCE(CASE WHEN smm.is_published IS TRUE THEN COALESCE(mm.score, (
                                SELECT COALESCE(SUM(mr.round_score), 0)
                                FROM mindmaze_results mr
                                JOIN mindmaze_rounds mrd ON mrd.round_id = mr.round_id
                                WHERE mrd.session_id = smm.session_id AND mr.team_id = t.team_id
                            ), 0) ELSE 0 END, 0) +
                            COALESCE(CASE WHEN sas.is_published IS TRUE THEN COALESCE(as_.score, (
                                SELECT COALESCE(SUM(asr.round_score), 0)
                                FROM ace_spade_results asr
                                JOIN ace_spade_rounds asrd ON asrd.round_id = asr.round_id
                                WHERE asrd.session_id = sas.session_id AND asr.team_id = t.team_id
                            ), 0) ELSE 0 END, 0) +
                            COALESCE(CASE WHEN skd.is_published IS TRUE THEN COALESCE(kd.score, GREATEST(0.0,
                                COALESCE(NULLIF((SELECT COUNT(*) FROM king_diamond_rounds WHERE session_id = skd.session_id), 0), 5) * 20.0
                                - COALESCE((
                                    SELECT SUM(kds.round_score)
                                    FROM king_diamond_submissions kds
                                    JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
                                    WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
                                ), 0.0)
                            )) ELSE 0 END, 0) +
                            COALESCE(CASE WHEN sjh.is_published IS TRUE THEN COALESCE(jh.score, (
                                SELECT COALESCE(SUM(jha.round_score), 0)
                                FROM jack_heart_answers jha
                                JOIN jack_heart_rounds jhr ON jhr.round_id = jha.round_id
                                WHERE jhr.session_id = sjh.session_id AND jha.team_id = t.team_id
                            ), 0) ELSE 0 END, 0)
                        ) DESC, t.team_code
                    )::INT
                ELSE NULL
            END AS live_rank,
                CASE
                    WHEN (rd.results_published_at IS NOT NULL) THEN
                        CASE WHEN rr.tiebreak_pending IS TRUE THEN NULL ELSE COALESCE(rr.is_qualified, FALSE) END
                    ELSE NULL
                END AS is_qualified,
                (rd.results_published_at IS NOT NULL) AS is_published,
                COALESCE(rr.tiebreak_pending, FALSE) AS tiebreak_pending,
                FLOOR(EXTRACT(EPOCH FROM rd.results_published_at) * 1000)::BIGINT AS results_broadcast_id
            FROM teams t
            JOIN round1_selections rs ON rs.team_id = t.team_id AND rs.room_id = :room_id
            LEFT JOIN suits st ON st.suit_id = rs.suit_id
            JOIN rooms r ON r.room_id = rs.room_id
            JOIN rounds rd ON rd.round_id = r.round_id
            LEFT JOIN game_sessions smm ON smm.room_id = r.room_id
                   AND smm.game_id = (SELECT game_id FROM games WHERE code = 'MINDMAZE')
            LEFT JOIN game_scores mm ON mm.session_id = smm.session_id AND mm.team_id = t.team_id
            LEFT JOIN game_sessions sas ON sas.room_id = r.room_id
                   AND sas.game_id = (SELECT game_id FROM games WHERE code = 'ACE_SPADE')
            LEFT JOIN game_scores as_ ON as_.session_id = sas.session_id AND as_.team_id = t.team_id
            LEFT JOIN game_sessions skd ON skd.room_id = r.room_id
                   AND skd.game_id = (SELECT game_id FROM games WHERE code = 'KING_DIAMOND')
            LEFT JOIN game_scores kd ON kd.session_id = skd.session_id AND kd.team_id = t.team_id
            LEFT JOIN game_sessions sjh ON sjh.room_id = r.room_id
                   AND sjh.game_id = (SELECT game_id FROM games WHERE code = 'JACK_HEART')
            LEFT JOIN game_scores jh ON jh.session_id = sjh.session_id AND jh.team_id = t.team_id
            LEFT JOIN room_results rr ON rr.room_id = r.room_id AND rr.team_id = t.team_id
            ORDER BY live_rank;
        """)
        rows = (await db.execute(query, {"room_id": str(room_id)})).mappings().all()
        return [dict(row) for row in rows]


async def _fetch_overall_leaderboard() -> list[dict]:
    async with async_session_maker() as db:
        query = text("""
            SELECT
                t.team_code,
                t.team_name,
                st.code AS team_suit_code,
                st.symbol AS team_suit_symbol,
                COALESCE(r.room_code, '—') AS room_code,
            CASE
                WHEN smm.is_published IS TRUE THEN
                    COALESCE(mm.score, (
                        SELECT COALESCE(SUM(mr.round_score), 0)
                        FROM mindmaze_results mr
                        JOIN mindmaze_rounds mrd ON mrd.round_id = mr.round_id
                        WHERE mrd.session_id = smm.session_id AND mr.team_id = t.team_id
                    ), 0)::FLOAT
                ELSE NULL
            END AS mindmaze_score,
            CASE
                WHEN sas.is_published IS TRUE THEN
                    COALESCE(as_.score, (
                        SELECT COALESCE(SUM(asr.round_score), 0)
                        FROM ace_spade_results asr
                        JOIN ace_spade_rounds asrd ON asrd.round_id = asr.round_id
                        WHERE asrd.session_id = sas.session_id AND asr.team_id = t.team_id
                    ), 0)::FLOAT
                ELSE NULL
            END AS ace_spade_score,
            CASE
                WHEN skd.is_published IS TRUE THEN
                    COALESCE(kd.score, GREATEST(0.0,
                        COALESCE(NULLIF((SELECT COUNT(*) FROM king_diamond_rounds WHERE session_id = skd.session_id), 0), 5) * 20.0
                        - COALESCE((
                            SELECT SUM(kds.round_score)
                            FROM king_diamond_submissions kds
                            JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
                            WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
                        ), 0.0)
                    ))::FLOAT
                ELSE NULL
            END AS king_diamond_score,
            CASE
                WHEN sjh.is_published IS TRUE THEN
                    COALESCE(jh.score, (
                        SELECT COALESCE(SUM(jha.round_score), 0)
                        FROM jack_heart_answers jha
                        JOIN jack_heart_rounds jhr ON jhr.round_id = jha.round_id
                        WHERE jhr.session_id = sjh.session_id AND jha.team_id = t.team_id
                    ), 0)::FLOAT
                ELSE NULL
            END AS jack_heart_score,
            CASE
                WHEN (smm.is_published IS TRUE OR sas.is_published IS TRUE OR skd.is_published IS TRUE OR sjh.is_published IS TRUE) THEN
                    (
                        COALESCE(CASE WHEN smm.is_published IS TRUE THEN COALESCE(mm.score, (
                            SELECT COALESCE(SUM(mr.round_score), 0)
                            FROM mindmaze_results mr
                            JOIN mindmaze_rounds mrd ON mrd.round_id = mr.round_id
                            WHERE mrd.session_id = smm.session_id AND mr.team_id = t.team_id
                        ), 0) ELSE 0 END, 0) +
                        COALESCE(CASE WHEN sas.is_published IS TRUE THEN COALESCE(as_.score, (
                            SELECT COALESCE(SUM(asr.round_score), 0)
                            FROM ace_spade_results asr
                            JOIN ace_spade_rounds asrd ON asrd.round_id = asr.round_id
                            WHERE asrd.session_id = sas.session_id AND asr.team_id = t.team_id
                        ), 0) ELSE 0 END, 0) +
                        COALESCE(CASE WHEN skd.is_published IS TRUE THEN COALESCE(kd.score, GREATEST(0.0,
                            COALESCE(NULLIF((SELECT COUNT(*) FROM king_diamond_rounds WHERE session_id = skd.session_id), 0), 5) * 20.0
                            - COALESCE((
                                SELECT SUM(kds.round_score)
                                FROM king_diamond_submissions kds
                                JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
                                WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
                            ), 0.0)
                        )) ELSE 0 END, 0) +
                        COALESCE(CASE WHEN sjh.is_published IS TRUE THEN COALESCE(jh.score, (
                            SELECT COALESCE(SUM(jha.round_score), 0)
                            FROM jack_heart_answers jha
                            JOIN jack_heart_rounds jhr ON jhr.round_id = jha.round_id
                            WHERE jhr.session_id = sjh.session_id AND jha.team_id = t.team_id
                        ), 0) ELSE 0 END, 0)
                    )::FLOAT
                ELSE NULL
            END AS total_score,
            CASE
                WHEN (rd.results_published_at IS NOT NULL) THEN
                    CASE WHEN rr.tiebreak_pending IS TRUE THEN NULL ELSE COALESCE(rr.is_qualified, FALSE) END
                ELSE NULL
            END AS is_qualified,
            CASE
                WHEN (smm.is_published IS TRUE OR sas.is_published IS TRUE OR skd.is_published IS TRUE OR sjh.is_published IS TRUE) THEN
                    RANK() OVER (
                        ORDER BY (
                            COALESCE(CASE WHEN smm.is_published IS TRUE THEN COALESCE(mm.score, (
                                SELECT COALESCE(SUM(mr.round_score), 0)
                                FROM mindmaze_results mr
                                JOIN mindmaze_rounds mrd ON mrd.round_id = mr.round_id
                                WHERE mrd.session_id = smm.session_id AND mr.team_id = t.team_id
                            ), 0) ELSE 0 END, 0) +
                            COALESCE(CASE WHEN sas.is_published IS TRUE THEN COALESCE(as_.score, (
                                SELECT COALESCE(SUM(asr.round_score), 0)
                                FROM ace_spade_results asr
                                JOIN ace_spade_rounds asrd ON asrd.round_id = asr.round_id
                                WHERE asrd.session_id = sas.session_id AND asr.team_id = t.team_id
                            ), 0) ELSE 0 END, 0) +
                            COALESCE(CASE WHEN skd.is_published IS TRUE THEN COALESCE(kd.score, GREATEST(0.0,
                                COALESCE(NULLIF((SELECT COUNT(*) FROM king_diamond_rounds WHERE session_id = skd.session_id), 0), 5) * 20.0
                                - COALESCE((
                                    SELECT SUM(kds.round_score)
                                    FROM king_diamond_submissions kds
                                    JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
                                    WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
                                ), 0.0)
                            )) ELSE 0 END, 0) +
                            COALESCE(CASE WHEN sjh.is_published IS TRUE THEN COALESCE(jh.score, (
                                SELECT COALESCE(SUM(jha.round_score), 0)
                                FROM jack_heart_answers jha
                                JOIN jack_heart_rounds jhr ON jhr.round_id = jha.round_id
                                WHERE jhr.session_id = sjh.session_id AND jha.team_id = t.team_id
                            ), 0) ELSE 0 END, 0)
                        ) DESC, t.team_code
                    )::INT
                ELSE NULL
            END AS overall_rank,
                (rd.results_published_at IS NOT NULL) AS is_published,
                COALESCE(rr.tiebreak_pending, FALSE) AS tiebreak_pending,
                FLOOR(EXTRACT(EPOCH FROM rd.results_published_at) * 1000)::BIGINT AS results_broadcast_id
            FROM teams t
            LEFT JOIN round1_selections rs ON rs.team_id = t.team_id
            LEFT JOIN suits st ON st.suit_id = rs.suit_id
            LEFT JOIN rooms r ON r.room_id = rs.room_id
            LEFT JOIN rounds rd ON rd.round_id = r.round_id
            LEFT JOIN game_sessions smm ON smm.room_id = r.room_id
                   AND smm.game_id = (SELECT game_id FROM games WHERE code = 'MINDMAZE')
            LEFT JOIN game_scores mm ON mm.session_id = smm.session_id AND mm.team_id = t.team_id
            LEFT JOIN game_sessions sas ON sas.room_id = r.room_id
                   AND sas.game_id = (SELECT game_id FROM games WHERE code = 'ACE_SPADE')
            LEFT JOIN game_scores as_ ON as_.session_id = sas.session_id AND as_.team_id = t.team_id
            LEFT JOIN game_sessions skd ON skd.room_id = r.room_id
                   AND skd.game_id = (SELECT game_id FROM games WHERE code = 'KING_DIAMOND')
            LEFT JOIN game_scores kd ON kd.session_id = skd.session_id AND kd.team_id = t.team_id
            LEFT JOIN game_sessions sjh ON sjh.room_id = r.room_id
                   AND sjh.game_id = (SELECT game_id FROM games WHERE code = 'JACK_HEART')
            LEFT JOIN game_scores jh ON jh.session_id = sjh.session_id AND jh.team_id = t.team_id
            LEFT JOIN room_results rr ON rr.room_id = r.room_id AND rr.team_id = t.team_id
            ORDER BY overall_rank;
        """)
        rows = (await db.execute(query)).mappings().all()
        return [dict(row) for row in rows]


def _decode_ws_token(token: str | None) -> dict | None:
    """Validate the bearer token from the WS query param. Returns payload or None."""
    if not token:
        return None
    try:
        return decode_token(token)
    except (ValueError, Exception):
        return None


async def _team_room(team_id: uuid.UUID, round_id_hint: uuid.UUID | None = None) -> uuid.UUID | None:
    """Return the room_id the team is assigned to (latest selection), or None."""
    async with async_session_maker() as db:
        stmt = (
            select(Round1Selection.room_id)
            .where(Round1Selection.team_id == team_id)
            .order_by(Round1Selection.selected_at.desc())
            .limit(1)
        )
        result = (await db.execute(stmt)).scalar_one_or_none()
        return result


@router.websocket("/ws/rooms/{room_id}/leaderboard")
async def room_leaderboard_ws(
    websocket: WebSocket,
    room_id: uuid.UUID,
    token: str | None = Query(default=None),
):
    # Fix §1.2: validate token before accepting.
    payload = _decode_ws_token(token)
    if payload is None:
        await websocket.close(code=4001, reason="Missing or invalid token")
        return

    token_type = payload.get("type")
    team_code = None
    if token_type == "team":
        # Team users: must be assigned to this specific room.
        team_id_str = payload.get("sub")
        if not team_id_str:
            await websocket.close(code=4003, reason="Invalid token payload")
            return
        try:
            team_id = uuid.UUID(team_id_str)
        except ValueError:
            await websocket.close(code=4003, reason="Invalid token payload")
            return
        assigned_room = await _team_room(team_id)
        if assigned_room is None or assigned_room != room_id:
            await websocket.close(code=4003, reason="Your team is not assigned to this room")
            return
        team_code = await _resolve_team_code(payload)
    elif token_type == "admin":
        # Admin users: allow any room (room binding enforced at REST layer).
        pass
    else:
        await websocket.close(code=4001, reason="Unknown token type")
        return

    await websocket.accept()
    if team_code:
        await _record_team_ws_connect(team_code, room_id)

    redis_client = redis.from_url(settings.redis_url)
    pubsub = redis_client.pubsub()
    channel = f"room:{room_id}:leaderboard"
    await pubsub.subscribe(channel)

    try:
        await websocket.send_text(json.dumps(await _fetch_room_leaderboard(room_id), default=str))

        async def relay():
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = await _fetch_room_leaderboard(room_id)
                    await websocket.send_text(json.dumps(data, default=str))

        relay_task = asyncio.create_task(relay())
        try:
            while True:
                await websocket.receive_text()
                if team_code:
                    await _refresh_team_ws_presence(team_code)
        except WebSocketDisconnect:
            pass
        finally:
            relay_task.cancel()
            try:
                await relay_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("relay task raised while shutting down")
    finally:
        if team_code:
            await _record_team_ws_disconnect(team_code, room_id)
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        await redis_client.close()


@router.websocket("/ws/leaderboard/overall")
async def overall_leaderboard_ws(
    websocket: WebSocket,
    token: str | None = Query(default=None),
):
    # Fix §1.2: validate token before accepting.
    payload = _decode_ws_token(token)
    if payload is None:
        await websocket.close(code=4001, reason="Missing or invalid token")
        return
    token_type = payload.get("type")
    if token_type not in ("team", "admin"):
        await websocket.close(code=4001, reason="Unknown token type")
        return

    team_code = None
    if token_type == "team":
        team_code = await _resolve_team_code(payload)

    await websocket.accept()
    if team_code:
        await _record_team_ws_connect(team_code)

    redis_client = redis.from_url(settings.redis_url)
    pubsub = redis_client.pubsub()
    channel = "leaderboard:overall"
    await pubsub.subscribe(channel)

    try:
        await websocket.send_text(json.dumps(await _fetch_overall_leaderboard(), default=str))

        async def relay():
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = await _fetch_overall_leaderboard()
                    await websocket.send_text(json.dumps(data, default=str))

        relay_task = asyncio.create_task(relay())
        try:
            while True:
                await websocket.receive_text()
                if team_code:
                    await _refresh_team_ws_presence(team_code)
        except WebSocketDisconnect:
            pass
        finally:
            relay_task.cancel()
            try:
                await relay_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("relay task raised while shutting down")
    finally:
        if team_code:
            await _record_team_ws_disconnect(team_code)
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        await redis_client.close()


@router.websocket("/ws/rooms/{room_id}/sessions")
async def room_sessions_ws(
    websocket: WebSocket,
    room_id: uuid.UUID,
    token: str | None = Query(default=None),
):
    payload = _decode_ws_token(token)
    if payload is None:
        await websocket.close(code=4001, reason="Missing or invalid token")
        return

    token_type = payload.get("type")
    team_code = None
    if token_type == "team":
        team_code = await _resolve_team_code(payload)

    await websocket.accept()
    if team_code:
        await _record_team_ws_connect(team_code, room_id)

    redis_client = redis.from_url(settings.redis_url)
    pubsub = redis_client.pubsub()
    channel = f"room:{room_id}:sessions"
    await pubsub.subscribe(channel)

    try:
        await websocket.send_text(json.dumps({"event": "connected"}))

        async def relay():
            async for message in pubsub.listen():
                if message["type"] == "message":
                    await websocket.send_text(json.dumps({"event": "session_updated"}))

        relay_task = asyncio.create_task(relay())
        try:
            while True:
                await websocket.receive_text()
                if team_code:
                    await _refresh_team_ws_presence(team_code)
        except WebSocketDisconnect:
            pass
        finally:
            relay_task.cancel()
            try:
                await relay_task
            except asyncio.CancelledError:
                pass
    finally:
        if team_code:
            await _record_team_ws_disconnect(team_code, room_id)
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        await redis_client.close()

