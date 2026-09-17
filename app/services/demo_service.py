"""
Demo (practice) rounds — a full parallel play surface for MindMaze, King of
Diamonds and Jack of Hearts that teams can rehearse on, and that an admin
drives with the same start / pause / resume / restart controls as the real
thing.

THE INVARIANT THIS MODULE EXISTS TO GUARANTEE
---------------------------------------------
**A demo round never writes a single row to Postgres.**

Every piece of demo state — sub-rounds, deadlines, submissions, Jack of
Hearts card assignments, computed ranks and points — lives in Redis under
the `demo:` key prefix with a TTL. Nothing here touches `game_sessions`,
`game_scores`, `mindmaze_results`, `king_diamond_submissions`,
`jack_heart_answers`, `room_results`, or any leaderboard view, so a practice
round cannot contribute a point to a team's real standing, cannot flip a
room to COMPLETED, and cannot be picked up by `fn_compute_room_results`.

The only SQL this module issues is **read-only**: which rooms are in a
round, which teams are selected into a room, their suits, and the
`jh_symbols` card deck. Every such query goes through `select(...)`; there
is no `db.add`, no `db.commit`, no `db.execute(text(<DML>))` anywhere in
this file, and adding one would break the guarantee above.

Scoring reuses the real games' pure scoring helpers
(`mindmaze_service.compute_round_score`, `king_diamond_service`'s rank
penalty ladder, `jack_heart_service.compute_round_score`) so a practice
sub-round is scored by exactly the same rules the real one would be — the
numbers are just thrown away with the Redis key.

Sub-rounds close lazily, on read, rather than through APScheduler: the
scheduler's jobs are DB-writing by construction and its job store outlives
a practice run, so a demo that is simply abandoned would leave jobs behind.
Both the team app and the admin dashboard poll this surface every 1–2s, so
"close it when someone next looks at it (or when everyone has submitted)"
is both simpler and self-cleaning. `end_demo` and the TTL do the rest.
"""

import asyncio
import json
import logging
import random
import uuid
from datetime import datetime, timedelta, timezone

import redis.asyncio as redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models.game import Game, RoundGames
from app.models.jack_heart import JHSymbol
from app.models.round import Room
from app.models.selection import Round1Selection, Suit
from app.models.team import Team
from app.services import ace_spade_service, jack_heart_service, king_diamond_service, mindmaze_service

logger = logging.getLogger("round1.demo")

GAME_CODES = ("MINDMAZE", "ACE_SPADE", "KING_DIAMOND", "JACK_HEART")

# Practice state is disposable by design. Twelve hours comfortably outlives
# any single event day while guaranteeing a forgotten demo evaporates.
DEMO_TTL_SECONDS = 12 * 60 * 60

# Demo-specific grace period for lazy Redis cleanup (not API validation).
# API validation uses unified 30-second grace period across all games (game_auth.py).
# This 3s is only for demo sub-round closing on read (when someone next looks at it).
CLOSE_GRACE_SECONDS = 3

# Every sub-round starts on a 3-2-1 countdown, same as a real one.
START_LEAD_SECONDS = 3

DEMO_STATUS_NOT_STARTED = "NOT_STARTED"
DEMO_STATUS_IN_PROGRESS = "IN_PROGRESS"
DEMO_STATUS_PAUSED = "PAUSED"
DEMO_STATUS_COMPLETED = "COMPLETED"


# ---------------------------------------------------------------------------
# Redis plumbing
# ---------------------------------------------------------------------------

_client: redis.Redis | None = None


def _redis() -> redis.Redis:
    """One lazily-created client for the process. `decode_responses=True`
    so every read is a str and the JSON round-trip stays trivial."""
    global _client
    if _client is None:
        _client = redis.from_url(settings.redis_url, decode_responses=True)
    return _client


def _session_key(round_id, game_code: str, room_id) -> str:
    return f"demo:s:{round_id}:{game_code}:{room_id}"


def _subs_key(demo_round_id) -> str:
    return f"demo:sub:{demo_round_id}"


def _assign_key(demo_round_id) -> str:
    return f"demo:asg:{demo_round_id}"


def _round_index_key(demo_round_id) -> str:
    """Reverse index: a demo sub-round id -> the session key that owns it,
    so a team's submit call can resolve its session without scanning."""
    return f"demo:r:{demo_round_id}"


def _lock_key(session_key: str) -> str:
    return f"{session_key}:lock"


class _Lock:
    """Tiny Redis mutex around read-modify-write of one session blob.

    Submissions and card assignments live in their own hashes precisely so
    they never need this — only whole-blob rewrites (admin actions and
    sub-round closes) contend, and those are rare.
    """

    def __init__(self, session_key: str, timeout: float = 5.0):
        self.key = _lock_key(session_key)
        self.token = str(uuid.uuid4())
        self.timeout = timeout

    async def __aenter__(self):
        r = _redis()
        deadline = asyncio.get_running_loop().time() + self.timeout
        while True:
            if await r.set(self.key, self.token, nx=True, px=5000):
                return self
            if asyncio.get_running_loop().time() >= deadline:
                # Never deadlock an admin action on a stale lock; the 5s PX
                # expiry means the previous holder is gone or hung anyway.
                logger.warning("demo lock %s timed out, proceeding", self.key)
                return self
            await asyncio.sleep(0.02)

    async def __aexit__(self, *exc):
        r = _redis()
        try:
            if await r.get(self.key) == self.token:
                await r.delete(self.key)
        except Exception:
            logger.exception("failed releasing demo lock %s", self.key)
        return False


async def _read_session(session_key: str) -> dict | None:
    raw = await _redis().get(session_key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        logger.warning("corrupt demo session blob at %s, discarding", session_key)
        await _redis().delete(session_key)
        return None


async def _write_session(blob: dict) -> None:
    r = _redis()
    key = _session_key(blob["round_id"], blob["game_code"], blob["room_id"])
    pipe = r.pipeline()
    pipe.set(key, json.dumps(blob), ex=DEMO_TTL_SECONDS)
    for sub in blob.get("rounds", []):
        pipe.set(_round_index_key(sub["round_id"]), key, ex=DEMO_TTL_SECONDS)
    await pipe.execute()


async def _purge_session(blob: dict) -> None:
    """Delete a demo session and every artefact it produced."""
    r = _redis()
    key = _session_key(blob["round_id"], blob["game_code"], blob["room_id"])
    keys = [key]
    for sub in blob.get("rounds", []):
        keys += [
            _subs_key(sub["round_id"]),
            _assign_key(sub["round_id"]),
            _round_index_key(sub["round_id"]),
        ]
    if keys:
        await r.delete(*keys)


async def _purge_subround(sub: dict) -> None:
    await _redis().delete(_subs_key(sub["round_id"]), _assign_key(sub["round_id"]))


async def _read_submissions(demo_round_id) -> dict[str, dict]:
    raw = await _redis().hgetall(_subs_key(demo_round_id))
    out = {}
    for team_id, payload in (raw or {}).items():
        try:
            out[team_id] = json.loads(payload)
        except ValueError:
            continue
    return out


async def _write_submission(demo_round_id, team_id: str, payload: dict) -> None:
    r = _redis()
    key = _subs_key(demo_round_id)
    await r.hset(key, team_id, json.dumps(payload))
    await r.expire(key, DEMO_TTL_SECONDS)


async def _read_assignments(demo_round_id) -> dict[str, int]:
    raw = await _redis().hgetall(_assign_key(demo_round_id))
    return {t: int(v) for t, v in (raw or {}).items()}


async def _write_assignments(demo_round_id, mapping: dict[str, int]) -> None:
    if not mapping:
        return
    r = _redis()
    key = _assign_key(demo_round_id)
    await r.delete(key)
    await r.hset(key, mapping={t: str(v) for t, v in mapping.items()})
    await r.expire(key, DEMO_TTL_SECONDS)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _play_seconds(game_code: str, duration_minutes: int) -> int:
    """Same per-game pacing the real session uses — MindMaze and King of
    Diamonds are fixed-length auto-submit mini-games, Jack of Hearts takes
    the admin's duration."""
    if game_code == "MINDMAZE":
        return settings.mindmaze_round_seconds
    if game_code == "ACE_SPADE":
        return settings.ace_spade_round_seconds
    if game_code == "KING_DIAMOND":
        return settings.king_diamond_round_seconds
    return max(1, int(duration_minutes)) * 60


# ---------------------------------------------------------------------------
# Read-only DB lookups (rooms / roster / card deck)
# ---------------------------------------------------------------------------


async def _rooms_with_game(db: AsyncSession, *, round_id, game_code: str) -> list[tuple]:
    """Every room in this event round whose configured lineup includes
    game_code — the identical scoping `session_service` uses for a real
    round-wide action, so a demo reaches exactly the rooms the real game
    would."""
    game = (await db.execute(select(Game).where(Game.code == game_code))).scalar_one_or_none()
    if game is None:
        raise NotFoundError(f"Unknown game_code '{game_code}'")

    rows = (
        await db.execute(
            select(Room.room_id, Room.room_code, Room.room_number)
            .join(RoundGames, RoundGames.round_id == Room.round_id)
            .where(Room.round_id == round_id, RoundGames.game_id == game.game_id)
            .order_by(Room.room_number)
        )
    ).all()
    if not rows:
        raise NotFoundError(f"No rooms in this round have '{game_code}' in their lineup")
    return [(r.room_id, r.room_code or f"Room {r.room_number}") for r in rows]


async def _roster(db: AsyncSession, room_id) -> list[dict]:
    """Teams selected into this room, with their suit — read-only."""
    rows = (
        await db.execute(
            select(
                Team.team_id,
                Team.team_code,
                Team.team_name,
                Suit.code.label("suit_code"),
                Suit.symbol.label("suit_symbol"),
            )
            .join(Round1Selection, Round1Selection.team_id == Team.team_id)
            .outerjoin(Suit, Suit.suit_id == Round1Selection.suit_id)
            .where(Round1Selection.room_id == room_id)
            .order_by(Team.team_code)
        )
    ).all()
    SUIT_FALLBACKS = [('SPADE', '♠'), ('HEART', '♥'), ('DIAMOND', '♦'), ('CLUB', '♣')]
    out = []
    for idx, r in enumerate(rows):
        code = (r.suit_code or "").upper() or None
        sym = r.suit_symbol
        if not code or not sym:
            fb_code, fb_sym = SUIT_FALLBACKS[idx % 4]
            code = code or fb_code
            sym = sym or fb_sym
        out.append({
            "team_id": str(r.team_id),
            "team_code": r.team_code,
            "team_name": r.team_name,
            "suit_code": code,
            "suit_symbol": sym,
        })
    return out


async def _symbol_deck(db: AsyncSession) -> list[dict]:
    rows = (await db.execute(select(JHSymbol).order_by(JHSymbol.symbol_id))).scalars().all()
    return [
        {
            "symbol_id": s.symbol_id,
            "code": s.code,
            "label": s.label,
            "suit": (s.suit or "").upper() or None,
            "rank": s.rank,
        }
        for s in rows
    ]


def _draw_assignments(roster: list[dict], deck: list[dict]) -> dict[str, int]:
    """One card per team, drawn from that team's own suit — the same rule
    `session_service._assign_symbols` applies to a real Jack of Hearts
    round."""
    by_suit: dict[str, list[int]] = {}
    for card in deck:
        if card["suit"]:
            by_suit.setdefault(card["suit"], []).append(card["symbol_id"])
    all_ids = [c["symbol_id"] for c in deck]
    if not all_ids:
        return {}

    rng = random.SystemRandom()
    out = {}
    for team in roster:
        pool = by_suit.get(team["suit_code"] or "", []) or all_ids
        out[team["team_id"]] = rng.choice(pool)
    return out


# ---------------------------------------------------------------------------
# Sub-round construction and closing
# ---------------------------------------------------------------------------


def _new_subround(round_number: int, start: datetime | None, play_seconds: int) -> dict:
    return {
        "round_number": round_number,
        "round_id": str(uuid.uuid4()),
        "start_time": _iso(start),
        "deadline": _iso(start + timedelta(seconds=play_seconds)) if start else None,
        "is_closed": False,
        "average_value": None,
        "target_value": None,
        "results": {},  # team_id -> {score/penalty/rank/...}, Redis-only
    }


def _find_subround(blob: dict, round_number: int) -> dict:
    for sub in blob.get("rounds", []):
        if sub["round_number"] == round_number:
            return sub
    raise NotFoundError(f"Demo sub-round {round_number} not found")


def _close_mindmaze(blob: dict, sub: dict, submissions: dict[str, dict]) -> None:
    for team in blob["roster"]:
        team_id = team["team_id"]
        entry = submissions.get(team_id)
        if entry is None:
            sub["results"][team_id] = {
                "submitted": False,
                "score": 0.0,
                "correct_tiles": 0,
                "mistakes": 0,
            }
            continue
        sub["results"][team_id] = {
            "submitted": True,
            "score": mindmaze_service.compute_round_score(
                entry.get("correct_tiles", 0), entry.get("mistakes", 0)
            ),
            "correct_tiles": entry.get("correct_tiles", 0),
            "mistakes": entry.get("mistakes", 0),
        }


def _close_ace_spade(blob: dict, sub: dict, submissions: dict[str, dict]) -> None:
    for team in blob["roster"]:
        team_id = team["team_id"]
        entry = submissions.get(team_id)
        if entry is None:
            sub["results"][team_id] = {
                "submitted": False,
                "score": 0.0,
                "correct_picks": 0,
                "wrong_picks": 0,
            }
            continue
        sub["results"][team_id] = {
            "submitted": True,
            "score": ace_spade_service.compute_round_score(
                entry.get("correct_picks", 0), entry.get("wrong_picks", 0)
            ),
            "correct_picks": entry.get("correct_picks", 0),
            "wrong_picks": entry.get("wrong_picks", 0),
        }


def _close_king_diamond(blob: dict, sub: dict, submissions: dict[str, dict]) -> None:
    """Average of every submitted number, target = average x 0.8, nearest
    wins; each next-nearest team loses one more point than the team ahead of
    it. A team that never submitted forfeits the full base. Identical ladder
    to king_diamond_service.close_round — see _penalty_for_rank there."""
    valid = {t: e for t, e in submissions.items() if e.get("submitted_number") is not None}
    numbers = [float(e["submitted_number"]) for e in valid.values()]
    average = (sum(numbers) / len(numbers)) if numbers else None
    target = round(average * 0.8, 4) if average is not None else None

    sub["average_value"] = round(average, 4) if average is not None else None
    sub["target_value"] = target

    ranked = []
    if target is not None:
        ranked = sorted(
            (
                (team_id, abs(float(entry["submitted_number"]) - target))
                for team_id, entry in valid.items()
            ),
            key=lambda pair: pair[1],
        )

    rank_by_team = {}
    diff_by_team = {}
    current_rank = 1
    for idx, (team_id, diff) in enumerate(ranked):
        diff_by_team[team_id] = diff
        if idx > 0 and diff > ranked[idx - 1][1]:
            current_rank += 1
        rank_by_team[team_id] = current_rank

    for team in blob["roster"]:
        team_id = team["team_id"]
        entry = valid.get(team_id)
        rank = rank_by_team.get(team_id)
        penalty = king_diamond_service._round_score_for_rank(rank if entry else None)
        sub["results"][team_id] = {
            "submitted": entry is not None,
            "submitted_number": float(entry["submitted_number"]) if entry else None,
            "difference": round(diff_by_team[team_id], 4) if team_id in diff_by_team else None,
            "rank": rank,
            "penalty": round(penalty, 1),
            "score": round(penalty, 1),  # KD scores are deductions
            "is_winner": rank == 1,
        }


def _close_jack_heart(blob: dict, sub: dict, submissions: dict[str, dict], assignments: dict[str, int]) -> None:
    for team in blob["roster"]:
        team_id = team["team_id"]
        entry = submissions.get(team_id)
        actual = assignments.get(team_id)
        submitted_symbol = entry.get("submitted_symbol_id") if entry else None
        score = (
            jack_heart_service.compute_round_score(submitted_symbol, actual)
            if submitted_symbol is not None and actual is not None
            else 0.0
        )
        sub["results"][team_id] = {
            "submitted": entry is not None,
            "submitted_symbol_id": submitted_symbol,
            "actual_symbol_id": actual,
            "is_correct": bool(submitted_symbol is not None and submitted_symbol == actual),
            "score": score,
        }


async def _close_subround(blob: dict, sub: dict) -> None:
    """Compute and freeze one demo sub-round's results into the blob.

    Idempotent: recomputing from the same submissions hash yields the same
    numbers, so a double-close is harmless.
    """
    submissions = await _read_submissions(sub["round_id"])
    sub["results"] = {}

    if blob["game_code"] == "MINDMAZE":
        _close_mindmaze(blob, sub, submissions)
    elif blob["game_code"] == "ACE_SPADE":
        _close_ace_spade(blob, sub, submissions)
    elif blob["game_code"] == "KING_DIAMOND":
        _close_king_diamond(blob, sub, submissions)
    else:
        _close_jack_heart(blob, sub, submissions, await _read_assignments(sub["round_id"]))

    sub["is_closed"] = True


async def _all_submitted(blob: dict, sub: dict) -> bool:
    if not blob["roster"]:
        return False
    submissions = await _read_submissions(sub["round_id"])
    return all(team["team_id"] in submissions for team in blob["roster"])


async def _refresh(blob: dict) -> dict:
    """Lazy close pass: run every time a blob is read.

    Closes any open sub-round whose deadline has passed (plus grace) or
    whose whole roster has already submitted, then marks the demo COMPLETED
    once every sub-round is done. Persists only when something changed.
    """
    if blob["status"] in (DEMO_STATUS_PAUSED, DEMO_STATUS_NOT_STARTED):
        return blob

    now = _now()
    changed = False

    for sub in blob["rounds"]:
        if sub["is_closed"] or not sub["start_time"]:
            continue
        deadline = _parse(sub["deadline"])
        expired = deadline is not None and now >= deadline + timedelta(seconds=CLOSE_GRACE_SECONDS)
        if expired or await _all_submitted(blob, sub):
            await _close_subround(blob, sub)
            changed = True

    if blob["rounds"] and all(s["is_closed"] for s in blob["rounds"]):
        if blob["status"] != DEMO_STATUS_COMPLETED:
            blob["status"] = DEMO_STATUS_COMPLETED
            blob["end_time"] = _iso(now)
            changed = True

    if changed:
        await _write_session(blob)
    return blob


async def _load_live(round_id, game_code: str, room_id) -> dict | None:
    blob = await _read_session(_session_key(round_id, game_code, room_id))
    return await _refresh(blob) if blob else None


# ---------------------------------------------------------------------------
# Serialisation for the API
# ---------------------------------------------------------------------------


def _team_totals(blob: dict) -> dict[str, float]:
    """Cumulative practice score per team. King of Diamonds counts down from
    its base; the other two count up."""
    totals = {}
    for team in blob["roster"]:
        team_id = team["team_id"]
        if blob["game_code"] == "KING_DIAMOND":
            spent = sum(
                float(s["results"].get(team_id, {}).get("penalty", 0.0))
                for s in blob["rounds"]
                if s["is_closed"]
            )
            num_rounds = blob.get("num_rounds") or len(blob.get("rounds", [])) or 1
            total_base = float(num_rounds * king_diamond_service.BASE_POINTS)
            totals[team_id] = max(0.0, total_base - spent)
        else:
            totals[team_id] = sum(
                float(s["results"].get(team_id, {}).get("score", 0.0))
                for s in blob["rounds"]
                if s["is_closed"]
            )
    return totals


async def _serialize_for_team(blob: dict, team_id: str) -> dict:
    """Shaped like a real `SessionOut` from `GET /rooms/{id}/sessions` so the
    team app's game shell can drive a practice round through exactly the
    same code path — with `is_demo` set so it can say so loudly on screen.

    `submitted` is read from the live submissions hash, not from the closed
    sub-round's results, because the shell decides between "show the game
    board" and "show the waiting screen" from it: sourcing it from the
    results would hand the board back to a team that had already played,
    for the whole gap between their submission and the sub-round closing.
    """
    rounds = []
    for sub in blob["rounds"]:
        result = sub["results"].get(team_id, {}) if sub["is_closed"] else {}
        correct_picks = None
        wrong_picks = None
        if sub["is_closed"]:
            submitted = bool(result.get("submitted"))
            score = result.get("score")
            mistakes = result.get("mistakes")
            correct_tiles = result.get("correct_tiles")
            if blob["game_code"] == "ACE_SPADE":
                correct_picks = result.get("correct_picks")
                wrong_picks = result.get("wrong_picks")
        else:
            live = (await _read_submissions(sub["round_id"])).get(team_id)
            submitted = live is not None
            mistakes = live.get("mistakes") if live else None
            correct_tiles = live.get("correct_tiles") if live else None
            # MindMaze and Ace of Spades are scored purely from a team's own
            # board, so their sub-round score is already final at submit
            # time. The other two depend on what everyone else did and stay
            # unknown until close.
            if live is not None and blob["game_code"] == "MINDMAZE":
                score = mindmaze_service.compute_round_score(correct_tiles or 0, mistakes or 0)
            elif live is not None and blob["game_code"] == "ACE_SPADE":
                correct_picks = live.get("correct_picks")
                wrong_picks = live.get("wrong_picks")
                score = ace_spade_service.compute_round_score(correct_picks or 0, wrong_picks or 0)
            else:
                score = None
        rounds.append(
            {
                "round_number": sub["round_number"],
                "round_id": sub["round_id"],
                "start_time": sub["start_time"],
                "deadline": sub["deadline"],
                "is_closed": sub["is_closed"],
                "submitted": submitted,
                "score": score,
                "mistakes": mistakes,
                "correct_tiles": correct_tiles,
                "correct_picks": correct_picks,
                "wrong_picks": wrong_picks,
            }
        )

    return {
        "is_demo": True,
        "demo_attempt": blob["attempt"],
        "session_id": blob["demo_session_id"],
        "round_id": blob["round_id"],
        "room_id": blob["room_id"],
        "room_code": blob["room_code"],
        "game_code": blob["game_code"],
        "status": blob["status"],
        "start_time": blob["start_time"],
        "end_time": blob.get("end_time"),
        "paused_at": blob.get("paused_at"),
        "instruction_until": None,
        "is_published": blob["status"] == DEMO_STATUS_COMPLETED,
        "total_room_teams": len(blob["roster"]),
        "rounds": rounds,
    }


async def _serialize_for_admin(blob: dict) -> dict:
    # Live submissions, so the dashboard's "3 / 8 submitted" counter moves
    # while the sub-round is still running rather than jumping at close.
    submitted_by_round = {}
    for sub in blob["rounds"]:
        landed = await _read_submissions(sub["round_id"])
        submitted_by_round[sub["round_id"]] = [
            team["team_code"] for team in blob["roster"] if team["team_id"] in landed
        ]

    return {
        "demo_session_id": blob["demo_session_id"],
        "round_id": blob["round_id"],
        "room_id": blob["room_id"],
        "room_code": blob["room_code"],
        "game_code": blob["game_code"],
        "status": blob["status"],
        "attempt": blob["attempt"],
        "start_time": blob["start_time"],
        "paused_at": blob.get("paused_at"),
        "total_room_teams": len(blob["roster"]),
        "rounds": [
            {
                "round_number": sub["round_number"],
                "round_id": sub["round_id"],
                "start_time": sub["start_time"],
                "deadline": sub["deadline"],
                "is_closed": sub["is_closed"],
                "submitted_teams": submitted_by_round.get(sub["round_id"], []),
            }
            for sub in blob["rounds"]
        ],
    }


# ---------------------------------------------------------------------------
# Admin control — round-wide fan-out, one room at a time
# ---------------------------------------------------------------------------


async def _publish_room(room_id) -> None:
    """Reuses the existing room sessions channel so team apps already
    listening on it re-poll and pick the demo up instantly — no new
    WebSocket endpoint needed. Goes through this module's pooled client
    rather than jobs._publish, which opens a fresh connection per call and
    would be doing so on every practice submission."""
    try:
        await _redis().publish(f"room:{room_id}:sessions", "updated")
    except Exception:
        logger.exception("failed publishing demo update for room %s", room_id)


async def _fan_out(db: AsyncSession, *, round_id, game_code: str, action) -> list[dict]:
    rooms = await _rooms_with_game(db, round_id=round_id, game_code=game_code)
    results = []
    for room_id, room_code in rooms:
        try:
            await action(room_id, room_code)
            results.append({"room_id": str(room_id), "room_code": room_code, "ok": True})
            await _publish_room(room_id)
        except (ConflictError, NotFoundError) as exc:
            results.append(
                {"room_id": str(room_id), "room_code": room_code, "ok": False, "reason": str(exc)}
            )
    return results


async def _build_session(
    db: AsyncSession,
    *,
    round_id,
    game_code: str,
    room_id,
    room_code: str,
    duration_minutes: int,
    num_rounds: int,
    attempt: int,
) -> dict:
    roster = await _roster(db, room_id)
    play_seconds = _play_seconds(game_code, duration_minutes)
    now = _now()
    first_start = now + timedelta(seconds=START_LEAD_SECONDS)

    blob = {
        "demo_session_id": str(uuid.uuid4()),
        "round_id": str(round_id),
        "room_id": str(room_id),
        "room_code": room_code,
        "game_code": game_code,
        "status": DEMO_STATUS_IN_PROGRESS,
        "attempt": attempt,
        "num_rounds": num_rounds,
        "play_seconds": play_seconds,
        "duration_minutes": duration_minutes,
        "start_time": _iso(now),
        "paused_at": None,
        "end_time": None,
        "roster": roster,
        "rounds": [
            _new_subround(i, first_start if i == 1 else None, play_seconds)
            for i in range(1, num_rounds + 1)
        ],
    }

    if game_code == "JACK_HEART":
        deck = await _symbol_deck(db)
        for sub in blob["rounds"]:
            await _write_assignments(sub["round_id"], _draw_assignments(roster, deck))

    await _write_session(blob)
    return blob


async def start_demo(
    db: AsyncSession,
    *,
    round_id,
    game_code: str,
    duration_minutes: int,
    num_rounds: int,
) -> list[dict]:
    """Arms a practice run of game_code in every room in this round. Refuses
    if one is already live — restart it instead, which is the "let them
    practise again" path."""

    async def action(room_id, room_code):
        key = _session_key(round_id, game_code, room_id)
        async with _Lock(key):
            existing = await _read_session(key)
            if existing is not None and existing["status"] in (
                DEMO_STATUS_IN_PROGRESS,
                DEMO_STATUS_PAUSED,
            ):
                raise ConflictError("A demo round is already running in this room")
            attempt = (existing["attempt"] + 1) if existing else 1
            if existing is not None:
                await _purge_session(existing)
            await _build_session(
                db,
                round_id=round_id,
                game_code=game_code,
                room_id=room_id,
                room_code=room_code,
                duration_minutes=duration_minutes,
                num_rounds=num_rounds,
                attempt=attempt,
            )

    return await _fan_out(db, round_id=round_id, game_code=game_code, action=action)


async def restart_demo(
    db: AsyncSession,
    *,
    round_id,
    game_code: str,
    duration_minutes: int | None = None,
    num_rounds: int | None = None,
) -> list[dict]:
    """"Let's run that again." Throws away the previous attempt entirely —
    submissions, cards, points — and deals a fresh one, keeping the same
    shape unless the admin passes new numbers. This is the control the
    practice loop is built around, so it works from any state, including a
    finished or never-started demo."""

    async def action(room_id, room_code):
        key = _session_key(round_id, game_code, room_id)
        async with _Lock(key):
            existing = await _read_session(key)
            attempt = (existing["attempt"] + 1) if existing else 1
            rounds = num_rounds or (existing["num_rounds"] if existing else 1)
            minutes = duration_minutes or (existing["duration_minutes"] if existing else 1)
            if existing is not None:
                await _purge_session(existing)
            await _build_session(
                db,
                round_id=round_id,
                game_code=game_code,
                room_id=room_id,
                room_code=room_code,
                duration_minutes=minutes,
                num_rounds=rounds,
                attempt=attempt,
            )

    return await _fan_out(db, round_id=round_id, game_code=game_code, action=action)


async def end_demo(db: AsyncSession, *, round_id, game_code: str) -> list[dict]:
    """Tears the practice surface down so team screens fall straight back to
    the real session (or its waiting screen). Deletes every Redis key the
    demo created."""

    async def action(room_id, room_code):
        key = _session_key(round_id, game_code, room_id)
        async with _Lock(key):
            existing = await _read_session(key)
            if existing is None:
                raise NotFoundError("No demo round in this room")
            await _purge_session(existing)

    return await _fan_out(db, round_id=round_id, game_code=game_code, action=action)


async def pause_demo(db: AsyncSession, *, round_id, game_code: str) -> list[dict]:
    async def action(room_id, room_code):
        key = _session_key(round_id, game_code, room_id)
        async with _Lock(key):
            blob = await _read_session(key)
            if blob is None:
                raise NotFoundError("No demo round in this room")
            if blob["status"] != DEMO_STATUS_IN_PROGRESS:
                raise ConflictError(f"Demo is {blob['status']}, not IN_PROGRESS")
            blob["status"] = DEMO_STATUS_PAUSED
            blob["paused_at"] = _iso(_now())
            await _write_session(blob)

    return await _fan_out(db, round_id=round_id, game_code=game_code, action=action)


async def resume_demo(db: AsyncSession, *, round_id, game_code: str) -> list[dict]:
    """Gives back exactly the time the pause consumed, the same way
    session_service.resume_session does for a real round."""

    async def action(room_id, room_code):
        key = _session_key(round_id, game_code, room_id)
        async with _Lock(key):
            blob = await _read_session(key)
            if blob is None:
                raise NotFoundError("No demo round in this room")
            if blob["status"] != DEMO_STATUS_PAUSED:
                raise ConflictError(f"Demo is {blob['status']}, not PAUSED")

            now = _now()
            paused_at = _parse(blob.get("paused_at")) or now
            elapsed = now - paused_at
            for sub in blob["rounds"]:
                if sub["is_closed"] or not sub["start_time"]:
                    continue
                start = _parse(sub["start_time"])
                deadline = _parse(sub["deadline"])
                if start:
                    sub["start_time"] = _iso(start + elapsed)
                if deadline:
                    shifted = deadline + elapsed
                    if shifted <= now:
                        shifted = now + timedelta(seconds=30)
                    sub["deadline"] = _iso(shifted)

            blob["status"] = DEMO_STATUS_IN_PROGRESS
            blob["paused_at"] = None
            await _write_session(blob)

    return await _fan_out(db, round_id=round_id, game_code=game_code, action=action)


async def start_demo_subround(
    db: AsyncSession, *, round_id, game_code: str, subround_number: int
) -> list[dict]:
    async def action(room_id, room_code):
        key = _session_key(round_id, game_code, room_id)
        async with _Lock(key):
            blob = await _read_session(key)
            if blob is None:
                raise NotFoundError("No demo round in this room")
            blob = await _refresh(blob)
            if blob["status"] == DEMO_STATUS_PAUSED:
                raise ConflictError("Resume the demo before starting a sub-round")
            sub = _find_subround(blob, subround_number)
            if sub["start_time"]:
                raise ConflictError(f"Demo sub-round {subround_number} has already started")

            start = _now() + timedelta(seconds=START_LEAD_SECONDS)
            sub["start_time"] = _iso(start)
            sub["deadline"] = _iso(start + timedelta(seconds=blob["play_seconds"]))
            blob["status"] = DEMO_STATUS_IN_PROGRESS
            blob["end_time"] = None
            await _write_session(blob)

    return await _fan_out(db, round_id=round_id, game_code=game_code, action=action)


async def restart_demo_subround(
    db: AsyncSession, *, round_id, game_code: str, subround_number: int
) -> list[dict]:
    """Replays a single practice sub-round: drops its submissions, redeals
    its Jack of Hearts cards, and puts a fresh timer on it."""

    async def action(room_id, room_code):
        key = _session_key(round_id, game_code, room_id)
        async with _Lock(key):
            blob = await _read_session(key)
            if blob is None:
                raise NotFoundError("No demo round in this room")
            sub = _find_subround(blob, subround_number)

            await _purge_subround(sub)
            if blob["game_code"] == "JACK_HEART":
                deck = await _symbol_deck(db)
                await _write_assignments(sub["round_id"], _draw_assignments(blob["roster"], deck))

            start = _now() + timedelta(seconds=START_LEAD_SECONDS)
            sub["start_time"] = _iso(start)
            sub["deadline"] = _iso(start + timedelta(seconds=blob["play_seconds"]))
            sub["is_closed"] = False
            sub["results"] = {}
            sub["average_value"] = None
            sub["target_value"] = None

            blob["status"] = DEMO_STATUS_IN_PROGRESS
            blob["end_time"] = None
            await _write_session(blob)

    return await _fan_out(db, round_id=round_id, game_code=game_code, action=action)


async def list_demo_for_round(db: AsyncSession, *, round_id, game_code: str) -> list[dict]:
    rooms = await _rooms_with_game(db, round_id=round_id, game_code=game_code)
    out = []
    for room_id, _room_code in rooms:
        blob = await _load_live(round_id, game_code, room_id)
        if blob is not None:
            out.append(await _serialize_for_admin(blob))
    return out


async def list_demo_overview(db: AsyncSession, *, round_id) -> list[dict]:
    """Every game's demo state for this round, for the admin dashboard."""
    out = []
    for game_code in GAME_CODES:
        try:
            out.extend(await list_demo_for_round(db, round_id=round_id, game_code=game_code))
        except NotFoundError:
            continue
    return out


# ---------------------------------------------------------------------------
# Team-facing surface
# ---------------------------------------------------------------------------


async def _assert_team_in_room(db: AsyncSession, *, team_id, room_id) -> None:
    selection = (
        await db.execute(
            select(Round1Selection).where(
                Round1Selection.team_id == team_id,
                Round1Selection.room_id == room_id,
            )
        )
    ).scalar_one_or_none()
    if selection is None:
        raise ForbiddenError("Your team is not assigned to this room")


async def list_team_demo_sessions(db: AsyncSession, *, room_id, team_id) -> list[dict]:
    await _assert_team_in_room(db, team_id=team_id, room_id=room_id)

    room = await db.get(Room, room_id)
    if room is None:
        raise NotFoundError("Room not found")

    out = []
    for game_code in GAME_CODES:
        blob = await _load_live(room.round_id, game_code, room_id)
        if blob is not None:
            out.append(await _serialize_for_team(blob, str(team_id)))
    return out


async def _resolve_subround(demo_round_id) -> tuple[dict, dict]:
    """demo sub-round id -> (session blob, that sub-round), via the reverse
    index written alongside every session."""
    session_key = await _redis().get(_round_index_key(demo_round_id))
    if not session_key:
        raise NotFoundError("Demo round not found or already ended")
    blob = await _read_session(session_key)
    if blob is None:
        raise NotFoundError("Demo round not found or already ended")
    blob = await _refresh(blob)
    for sub in blob["rounds"]:
        if sub["round_id"] == str(demo_round_id):
            return blob, sub
    raise NotFoundError("Demo round not found or already ended")


def _assert_can_submit(blob: dict, sub: dict, team_id: str) -> None:
    if blob["status"] == DEMO_STATUS_PAUSED:
        raise ConflictError("This demo round is paused by an admin")
    if not any(t["team_id"] == team_id for t in blob["roster"]):
        raise ForbiddenError("Your team is not in this demo round")
    if sub["is_closed"]:
        raise ConflictError("This demo sub-round is already closed")
    deadline = _parse(sub["deadline"])
    if deadline and _now() > deadline + timedelta(seconds=30):
        raise ConflictError("Submission deadline has passed")


async def submit_mindmaze(
    db: AsyncSession, *, demo_round_id, team_id, moves: int, mistakes: int, correct_tiles: int,
    completion_time_seconds: float | None,
) -> dict:
    blob, sub = await _resolve_subround(demo_round_id)
    team_key = str(team_id)
    _assert_can_submit(blob, sub, team_key)

    correct_tiles = max(0, min(int(correct_tiles), settings.mindmaze_max_tiles))
    mistakes = max(0, int(mistakes))
    payload = {
        "moves": max(int(moves), correct_tiles + mistakes),
        "mistakes": mistakes,
        "correct_tiles": correct_tiles,
        "completion_time_seconds": completion_time_seconds,
        "submitted_at": _iso(_now()),
    }
    await _write_submission(sub["round_id"], team_key, payload)

    await _publish_room(blob["room_id"])
    return {
        "round_id": sub["round_id"],
        "is_demo": True,
        "moves": payload["moves"],
        "mistakes": mistakes,
        "correct_tiles": correct_tiles,
        "round_score": mindmaze_service.compute_round_score(correct_tiles, mistakes),
        "submitted_at": payload["submitted_at"],
    }


async def submit_ace_spade(
    db: AsyncSession, *, demo_round_id, team_id, moves: int, wrong_picks: int, correct_picks: int,
    completion_time_seconds: float | None,
) -> dict:
    blob, sub = await _resolve_subround(demo_round_id)
    team_key = str(team_id)
    _assert_can_submit(blob, sub, team_key)

    correct_picks = max(0, min(int(correct_picks), settings.ace_spade_max_cards))
    wrong_picks = max(0, int(wrong_picks))
    payload = {
        "moves": max(int(moves), correct_picks + wrong_picks),
        "wrong_picks": wrong_picks,
        "correct_picks": correct_picks,
        "completion_time_seconds": completion_time_seconds,
        "submitted_at": _iso(_now()),
    }
    await _write_submission(sub["round_id"], team_key, payload)

    await _publish_room(blob["room_id"])
    return {
        "round_id": sub["round_id"],
        "is_demo": True,
        "moves": payload["moves"],
        "wrong_picks": wrong_picks,
        "correct_picks": correct_picks,
        "round_score": ace_spade_service.compute_round_score(correct_picks, wrong_picks),
        "submitted_at": payload["submitted_at"],
    }


async def submit_king_diamond(db: AsyncSession, *, demo_round_id, team_id, submitted_number: float) -> dict:
    blob, sub = await _resolve_subround(demo_round_id)
    team_key = str(team_id)
    _assert_can_submit(blob, sub, team_key)

    payload = {"submitted_number": float(submitted_number), "submitted_at": _iso(_now())}
    await _write_submission(sub["round_id"], team_key, payload)

    # Same early-close as the real game: once the whole room is in, there is
    # nothing left to wait for.
    if await _all_submitted(blob, sub):
        async with _Lock(_session_key(blob["round_id"], blob["game_code"], blob["room_id"])):
            fresh = await _read_session(_session_key(blob["round_id"], blob["game_code"], blob["room_id"]))
            if fresh is not None:
                target = next((s for s in fresh["rounds"] if s["round_id"] == sub["round_id"]), None)
                if target is not None and not target["is_closed"]:
                    await _close_subround(fresh, target)
                    if all(s["is_closed"] for s in fresh["rounds"]):
                        fresh["status"] = DEMO_STATUS_COMPLETED
                        fresh["end_time"] = _iso(_now())
                    await _write_session(fresh)

    await _publish_room(blob["room_id"])
    return {"round_id": sub["round_id"], "is_demo": True, "submitted_number": float(submitted_number)}


async def submit_jack_heart(db: AsyncSession, *, demo_round_id, team_id, submitted_symbol_id: int) -> dict:
    blob, sub = await _resolve_subround(demo_round_id)
    team_key = str(team_id)
    _assert_can_submit(blob, sub, team_key)

    payload = {"submitted_symbol_id": int(submitted_symbol_id), "submitted_at": _iso(_now())}
    await _write_submission(sub["round_id"], team_key, payload)

    await _publish_room(blob["room_id"])
    # The actual card is deliberately NOT echoed back — the whole game is
    # not knowing it until the sub-round closes.
    return {"round_id": sub["round_id"], "is_demo": True, "submitted_symbol_id": int(submitted_symbol_id)}


async def king_diamond_result(db: AsyncSession, *, demo_round_id, team_id) -> dict:
    """Practice twin of king_diamond_service.get_team_round_result — same
    payload shape so the team app's reveal animation runs unchanged."""
    blob, sub = await _resolve_subround(demo_round_id)
    team_key = str(team_id)

    totals = _team_totals(blob)
    result = sub["results"].get(team_key, {})
    all_submissions = []
    if sub["is_closed"]:
        for team in blob["roster"]:
            entry = sub["results"].get(team["team_id"], {})
            all_submissions.append(
                {
                    "team_code": team["team_code"],
                    "team_id": team["team_id"],
                    "submitted_number": entry.get("submitted_number"),
                    "is_valid": bool(entry.get("submitted")),
                    "difference": entry.get("difference"),
                    "rank": entry.get("rank"),
                    "penalty": entry.get("penalty", 0.0),
                    "round_score": entry.get("penalty", 0.0),
                    "is_you": team["team_id"] == team_key,
                }
            )
        all_submissions.sort(key=lambda s: (s["rank"] is None, s["rank"] or 0, s["team_code"]))

    num_rounds = blob.get("num_rounds") or len(blob.get("rounds", [])) or 1
    total_base = float(num_rounds * king_diamond_service.BASE_POINTS)

    return {
        "is_demo": True,
        "round_id": sub["round_id"],
        "round_number": sub["round_number"],
        "is_closed": sub["is_closed"],
        "average_value": sub["average_value"],
        "target_value": sub["target_value"],
        "submitted_number": result.get("submitted_number"),
        "difference": result.get("difference"),
        "rank": result.get("rank"),
        "round_score": round(totals.get(team_key, total_base), 1),
        "penalty": round(float(result.get("penalty", 0.0)), 1),
        "base_points": king_diamond_service.BASE_POINTS,
        "total_rounds": num_rounds,
        "total_base_points": total_base,
        "is_valid": bool(result.get("submitted")),
        "total_teams": len(blob["roster"]),
        "all_submissions": all_submissions,
    }


async def jack_heart_visible_symbols(db: AsyncSession, *, demo_round_id, team_id) -> list[dict]:
    """Every *other* team's practice card — never the caller's own, exactly
    like the real endpoint."""
    blob, sub = await _resolve_subround(demo_round_id)
    team_key = str(team_id)

    assignments = await _read_assignments(sub["round_id"])
    deck = {c["symbol_id"]: c for c in await _symbol_deck(db)}

    out = []
    for team in blob["roster"]:
        if team["team_id"] == team_key:
            continue
        symbol_id = assignments.get(team["team_id"])
        card = deck.get(symbol_id, {})
        out.append(
            {
                "team_id": team["team_id"],
                "team_code": team["team_code"],
                "team_name": team["team_name"],
                "team_suit_code": team["suit_code"] or card.get("suit"),
                "team_suit_symbol": team["suit_symbol"],
                "symbol_id": symbol_id,
                "symbol_code": card.get("code"),
                "symbol_label": card.get("label"),
                "suit": card.get("suit"),
                "rank": card.get("rank"),
            }
        )
    return out


async def jack_heart_my_suit(db: AsyncSession, *, demo_round_id, team_id) -> dict:
    blob, sub = await _resolve_subround(demo_round_id)
    team_key = str(team_id)
    team = next((t for t in blob["roster"] if t["team_id"] == team_key), None)

    suit_code = team["suit_code"] if team else None
    deck = await _symbol_deck(db)
    if not suit_code:
        assignments = await _read_assignments(sub["round_id"])
        symbol_id = assignments.get(team_key)
        suit_code = next((c["suit"] for c in deck if c["symbol_id"] == symbol_id), None)

    suit_symbols = {"HEART": "♥", "SPADE": "♠", "CLUB": "♣", "DIAMOND": "♦"}
    return {
        "is_demo": True,
        "suit_code": suit_code,
        "suit_symbol": (team["suit_symbol"] if team else None) or suit_symbols.get(suit_code or ""),
        "symbols": [c for c in deck if not suit_code or c["suit"] == suit_code],
    }


async def demo_leaderboard(db: AsyncSession, *, room_id, game_code: str, team_id) -> list[dict]:
    """Practice standings for one room. Purely a read of the Redis blob —
    it never appears in `room_results`, `v_room_leaderboard`, or the live
    scoreboard WebSocket."""
    await _assert_team_in_room(db, team_id=team_id, room_id=room_id)
    room = await db.get(Room, room_id)
    if room is None:
        raise NotFoundError("Room not found")

    blob = await _load_live(room.round_id, game_code, room_id)
    if blob is None:
        return []

    totals = _team_totals(blob)
    team_key = str(team_id)
    live_by_round = {
        sub["round_id"]: (set() if sub["is_closed"] else set(await _read_submissions(sub["round_id"])))
        for sub in blob["rounds"]
    }
    rows = []
    for team in blob["roster"]:
        subrounds = []
        for sub in blob["rounds"]:
            entry = sub["results"].get(team["team_id"], {})
            submitted = (
                bool(entry.get("submitted"))
                if sub["is_closed"]
                else team["team_id"] in live_by_round[sub["round_id"]]
            )
            subrounds.append(
                {
                    "round_number": sub["round_number"],
                    "is_closed": sub["is_closed"],
                    "submitted": submitted,
                    "score": float(entry.get("score", 0.0)) if sub["is_closed"] else 0.0,
                    "is_correct": entry.get("is_correct"),
                    "correct_tiles": entry.get("correct_tiles"),
                    "mistakes": entry.get("mistakes"),
                    "correct_picks": entry.get("correct_picks"),
                    "wrong_picks": entry.get("wrong_picks"),
                }
            )
        rows.append(
            {
                "is_demo": True,
                "team_id": team["team_id"],
                "team_code": team["team_code"],
                "team_name": team["team_name"],
                "team_suit_code": team["suit_code"],
                "team_suit_symbol": team["suit_symbol"],
                "subrounds": subrounds,
                "total_score": round(totals.get(team["team_id"], 0.0), 1),
                "is_current_team": team["team_id"] == team_key,
            }
        )

    # Higher is better in all three: MindMaze/Jack of Hearts accumulate
    # points, King of Diamonds reports the points a team has left.
    rows.sort(key=lambda r: (-r["total_score"], r["team_code"]))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows
