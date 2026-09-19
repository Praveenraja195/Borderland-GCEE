"""Death Card tiebreaker — rules, tie detection and result write-back.

Lifecycle
  publish            → detect_and_create(): a tie straddling the cutoff opens a
                       PENDING session; the tied teams' room_results are held
                       (tiebreak_pending) so their devices show the tiebreak
                       screen instead of a VISA / laser.
  admin "Start"      → start(): round 1 is dealt.
  every state read   → tick(): lazily resolves a round whose deadline passed
                       and deals the next one after the reveal pause, so the
                       game runs itself without the scheduler.
  Joker drawn        → that team is eliminated right away (its laser fires).
  survivors == slots → COMPLETED: winners qualify, ranks inside the tied group
                       are finalised (winners first, then losers by how long
                       they survived), holds released.
  any recompute      → apply_existing(): re-validates the session against the
                       fresh totals (VOID if the tie is gone) and re-applies
                       the holds / resolution, since fn_compute_room_results
                       overwrites rank + is_qualified every time.
"""

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import redis.asyncio as redis
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models.round import Room
from app.models.team import Team
from app.models.tiebreak import (
    TiebreakParticipant,
    TiebreakParticipantStatus,
    TiebreakPick,
    TiebreakRound,
    TiebreakSession,
    TiebreakStatus,
)

logger = logging.getLogger("round1.tiebreak")

ROUND_SECONDS = 20   # time to pick a card
REVEAL_SECONDS = 6   # pause after the reveal before the next round is dealt
MIN_CARDS = 3

ALIVE = TiebreakParticipantStatus.ALIVE.value
ELIMINATED = TiebreakParticipantStatus.ELIMINATED.value
WINNER = TiebreakParticipantStatus.WINNER.value

LIVE_STATUSES = (TiebreakStatus.PENDING.value, TiebreakStatus.ACTIVE.value, TiebreakStatus.COMPLETED.value)

# Same rule lookup fn_compute_room_results uses: room-specific rule, else the
# round default, else 1.
TOP_N_SQL = """
    SELECT COALESCE((
        SELECT qr.top_n
          FROM qualification_rules qr
          JOIN rooms rm ON rm.round_id = qr.round_id
         WHERE rm.room_id = :room_id
           AND (qr.room_id = :room_id OR qr.room_id IS NULL)
         ORDER BY qr.room_id NULLS LAST
         LIMIT 1), 1)
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _publish(channel: str) -> None:
    try:
        client = redis.from_url(settings.redis_url)
        await client.publish(channel, "updated")
        await client.close()
    except Exception:
        logger.exception("Failed to publish to redis channel %s", channel)


async def publish_room(room_id: uuid.UUID) -> None:
    """Nudge every live view of this room after a tiebreak state change."""
    await _publish(f"room:{room_id}:leaderboard")
    await _publish(f"room:{room_id}:sessions")
    await _publish("leaderboard:overall")


# --------------------------------------------------------------------------
# Tie detection
# --------------------------------------------------------------------------

async def _room_top_n(db: AsyncSession, room_id: uuid.UUID) -> int:
    return int((await db.execute(text(TOP_N_SQL), {"room_id": str(room_id)})).scalar() or 1)


async def _straddling_tie(db: AsyncSession, room_id: uuid.UUID, top_n: int) -> dict | None:
    """The group of equal-total teams that sits across the cutoff, if any.

    Ranks are recomputed here from total_score (RANK(), ties share a rank)
    rather than read from room_results.rank, which apply_existing() may have
    already rewritten for a resolved tiebreak."""
    rows = (
        await db.execute(
            text("""
                SELECT rr.team_id, rr.total_score,
                       RANK() OVER (ORDER BY rr.total_score DESC) AS rnk
                  FROM room_results rr
                 WHERE rr.room_id = :room_id
            """),
            {"room_id": str(room_id)},
        )
    ).all()
    groups: dict[int, list] = {}
    for team_id, total, rnk in rows:
        groups.setdefault(int(rnk), []).append((team_id, total))
    for rnk, members in groups.items():
        size = len(members)
        if size > 1 and rnk <= top_n < rnk + size - 1:
            return {
                "rank": rnk,
                "total": Decimal(str(members[0][1])),
                "team_ids": [m[0] for m in members],
                "slots": top_n - rnk + 1,
            }
    return None


async def _live_session(db: AsyncSession, room_id: uuid.UUID) -> TiebreakSession | None:
    return (
        await db.execute(
            select(TiebreakSession)
            .where(TiebreakSession.room_id == room_id, TiebreakSession.status.in_(LIVE_STATUSES))
            .order_by(TiebreakSession.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _participants(db: AsyncSession, session_id: uuid.UUID) -> list[TiebreakParticipant]:
    return list(
        (await db.execute(select(TiebreakParticipant).where(TiebreakParticipant.session_id == session_id))).scalars().all()
    )


async def detect_and_create(db: AsyncSession, *, room_id: uuid.UUID) -> TiebreakSession | None:
    """Called at publish, after the room's results are computed (same
    transaction). Opens a session for a tie at the cutoff, keeps a still-valid
    existing one, voids a stale one."""
    top_n = await _room_top_n(db, room_id)
    tie = await _straddling_tie(db, room_id, top_n)
    existing = await _live_session(db, room_id)

    if existing is not None:
        parts = await _participants(db, existing.session_id)
        same = (
            tie is not None
            and {p.team_id for p in parts} == set(tie["team_ids"])
            and Decimal(str(existing.tie_total)) == tie["total"]
        )
        if same:
            await apply_existing(db, room_id=room_id)
            return existing
        existing.status = TiebreakStatus.VOID.value
        await db.flush()

    if tie is None:
        await _clear_holds(db, room_id)
        return None

    room = await db.get(Room, room_id)
    session = TiebreakSession(
        room_id=room_id,
        round_id=room.round_id,
        tie_rank=tie["rank"],
        tie_total=tie["total"],
        slots=tie["slots"],
        status=TiebreakStatus.PENDING.value,
    )
    db.add(session)
    await db.flush()
    for team_id in tie["team_ids"]:
        db.add(TiebreakParticipant(session_id=session.session_id, team_id=team_id, status=ALIVE))
    await db.flush()
    await apply_existing(db, room_id=room_id)
    logger.info("Tiebreak opened for room %s: %s teams tied at %s for %s slot(s)",
                room_id, len(tie["team_ids"]), tie["total"], tie["slots"])
    return session


async def _clear_holds(db: AsyncSession, room_id: uuid.UUID) -> None:
    await db.execute(
        text("UPDATE room_results SET tiebreak_pending = FALSE WHERE room_id = :room_id AND tiebreak_pending"),
        {"room_id": str(room_id)},
    )


async def apply_existing(db: AsyncSession, *, room_id: uuid.UUID) -> None:
    """Re-apply the room's live tiebreak to room_results. Runs after every
    recompute (which resets rank/is_qualified from raw totals)."""
    session = await _live_session(db, room_id)
    if session is None:
        await _clear_holds(db, room_id)
        return

    parts = await _participants(db, session.session_id)
    top_n = await _room_top_n(db, room_id)
    tie = await _straddling_tie(db, room_id, top_n)
    valid = (
        tie is not None
        and {p.team_id for p in parts} == set(tie["team_ids"])
        and Decimal(str(session.tie_total)) == tie["total"]
    )
    if not valid:
        session.status = TiebreakStatus.VOID.value
        await db.flush()
        await _clear_holds(db, room_id)
        logger.info("Tiebreak %s voided: totals changed underneath it", session.session_id)
        return

    r, s = session.tie_rank, session.slots
    alive = sorted([p for p in parts if p.status == ALIVE], key=lambda p: str(p.team_id))
    winners = [p for p in parts if p.status == WINNER]
    losers = [p for p in parts if p.status == ELIMINATED]

    if session.status == TiebreakStatus.COMPLETED.value:
        # Winners take the top of the tied block (ordered by team code, they
        # are equals); losers follow, the longest survivor first.
        codes = {
            t.team_id: t.team_code
            for t in (await db.execute(select(Team).where(Team.team_id.in_([p.team_id for p in parts])))).scalars().all()
        }
        winners.sort(key=lambda p: codes.get(p.team_id, ""))
        losers.sort(key=lambda p: (-(p.eliminated_in_round or 0), codes.get(p.team_id, "")))
        rank = r
        for p in winners:
            await _set_result(db, room_id, p.team_id, rank=rank, qualified=True, pending=False)
            rank += 1
        for p in losers:
            await _set_result(db, room_id, p.team_id, rank=rank, qualified=False, pending=False)
            rank += 1
        return

    # PENDING / ACTIVE: alive teams are held; already-eliminated teams are out.
    for p in alive:
        await _set_result(db, room_id, p.team_id, rank=r, qualified=False, pending=True)
    for p in losers:
        await _set_result(db, room_id, p.team_id, rank=r + s, qualified=False, pending=False)


async def _set_result(db, room_id, team_id, *, rank, qualified, pending) -> None:
    await db.execute(
        text("""
            UPDATE room_results
               SET rank = :rank, is_qualified = :qualified, tiebreak_pending = :pending
             WHERE room_id = :room_id AND team_id = :team_id
        """),
        {"rank": rank, "qualified": qualified, "pending": pending, "room_id": str(room_id), "team_id": str(team_id)},
    )


# --------------------------------------------------------------------------
# Game flow
# --------------------------------------------------------------------------

async def _current_round(db: AsyncSession, session_id: uuid.UUID) -> TiebreakRound | None:
    return (
        await db.execute(
            select(TiebreakRound)
            .where(TiebreakRound.session_id == session_id)
            .order_by(TiebreakRound.round_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _deal_round(db: AsyncSession, session: TiebreakSession, round_number: int) -> TiebreakRound:
    alive = [p for p in await _participants(db, session.session_id) if p.status == ALIVE]
    card_count = max(MIN_CARDS, len(alive) + 1)
    now = _now()
    rnd = TiebreakRound(
        session_id=session.session_id,
        round_number=round_number,
        card_count=card_count,
        joker_index=secrets.randbelow(card_count),
        start_time=now,
        deadline=now + timedelta(seconds=ROUND_SECONDS),
    )
    db.add(rnd)
    await db.flush()
    return rnd


async def start(db: AsyncSession, session: TiebreakSession) -> None:
    if session.status != TiebreakStatus.PENDING.value:
        raise ConflictError(f"Tiebreak is {session.status}, not PENDING")
    session.status = TiebreakStatus.ACTIVE.value
    session.started_at = _now()
    await db.flush()
    await _deal_round(db, session, 1)


async def resolve_round(db: AsyncSession, session: TiebreakSession, rnd: TiebreakRound, *, force: bool = False) -> bool:
    """Reveal: deal leftover cards to teams that didn't pick, eliminate the
    Joker's holder, complete the session when survivors == slots. Returns
    True if this call did the resolution (it is race-safe: only the first
    caller wins the UPDATE ... WHERE is_resolved = FALSE)."""
    if rnd.is_resolved:
        return False
    if not force and _now() < rnd.deadline:
        return False
    claimed = (
        await db.execute(
            text("""
                UPDATE tiebreak_rounds SET is_resolved = TRUE, resolved_at = now()
                 WHERE round_id = :rid AND is_resolved = FALSE
             RETURNING round_id
            """),
            {"rid": str(rnd.round_id)},
        )
    ).scalar_one_or_none()
    if claimed is None:
        return False
    await db.refresh(rnd)

    parts = await _participants(db, session.session_id)
    alive = [p for p in parts if p.status == ALIVE]
    picks = list((await db.execute(select(TiebreakPick).where(TiebreakPick.round_id == rnd.round_id))).scalars().all())
    picked_by = {p.team_id: p for p in picks}
    taken = {p.card_index for p in picks}

    # Teams that never picked get a leftover card at random — same odds.
    free = [i for i in range(rnd.card_count) if i not in taken]
    for p in alive:
        if p.team_id in picked_by:
            continue
        idx = free.pop(secrets.randbelow(len(free)))
        pick = TiebreakPick(round_id=rnd.round_id, team_id=p.team_id, card_index=idx, auto_assigned=True)
        db.add(pick)
        picked_by[p.team_id] = pick
    await db.flush()

    loser = next((p for p in alive if picked_by[p.team_id].card_index == rnd.joker_index), None)
    if loser is not None:
        loser.status = ELIMINATED
        loser.eliminated_in_round = rnd.round_number
        rnd.eliminated_team_id = loser.team_id
        await db.flush()

    survivors = [p for p in parts if p.status == ALIVE]
    if len(survivors) <= session.slots:
        for p in survivors:
            p.status = WINNER
        session.status = TiebreakStatus.COMPLETED.value
        session.completed_at = _now()
        await db.flush()
    await apply_existing(db, room_id=session.room_id)
    return True


async def tick(db: AsyncSession, session: TiebreakSession) -> bool:
    """Lazy driver run on every state read: resolve an expired round, and
    deal the next one once the reveal pause is over. Returns True if the
    state changed (callers commit + publish)."""
    if session.status != TiebreakStatus.ACTIVE.value:
        return False
    changed = False
    rnd = await _current_round(db, session.session_id)
    if rnd is not None and not rnd.is_resolved and _now() >= rnd.deadline:
        changed = await resolve_round(db, session, rnd) or changed
        rnd = await _current_round(db, session.session_id)
    if (
        session.status == TiebreakStatus.ACTIVE.value
        and rnd is not None
        and rnd.is_resolved
        and rnd.resolved_at is not None
        and _now() >= rnd.resolved_at + timedelta(seconds=REVEAL_SECONDS)
    ):
        await _deal_round(db, session, rnd.round_number + 1)
        changed = True
    return changed


async def advance(db: AsyncSession, session: TiebreakSession) -> None:
    """Admin override: start / reveal now / deal the next round now."""
    if session.status == TiebreakStatus.PENDING.value:
        await start(db, session)
        return
    if session.status != TiebreakStatus.ACTIVE.value:
        raise ConflictError(f"Tiebreak is {session.status}")
    rnd = await _current_round(db, session.session_id)
    if rnd is None:
        await _deal_round(db, session, 1)
    elif not rnd.is_resolved:
        await resolve_round(db, session, rnd, force=True)
    else:
        await _deal_round(db, session, rnd.round_number + 1)


async def reset(db: AsyncSession, session: TiebreakSession) -> None:
    """Wipe every round and start over with the same tied teams."""
    if session.status == TiebreakStatus.VOID.value:
        raise ConflictError("Tiebreak is void")
    await db.execute(text("DELETE FROM tiebreak_rounds WHERE session_id = :sid"), {"sid": str(session.session_id)})
    for p in await _participants(db, session.session_id):
        p.status = ALIVE
        p.eliminated_in_round = None
    session.status = TiebreakStatus.PENDING.value
    session.started_at = None
    session.completed_at = None
    await db.flush()
    await apply_existing(db, room_id=session.room_id)


async def pick(db: AsyncSession, session: TiebreakSession, team_id: uuid.UUID, card_index: int) -> TiebreakPick:
    if session.status != TiebreakStatus.ACTIVE.value:
        raise ConflictError("Tiebreak is not running")
    rnd = await _current_round(db, session.session_id)
    if rnd is None or rnd.is_resolved or _now() >= rnd.deadline:
        raise ConflictError("This round is over")
    part = next((p for p in await _participants(db, session.session_id) if p.team_id == team_id), None)
    if part is None or part.status != ALIVE:
        raise ConflictError("You are not in this round")
    if not 0 <= card_index < rnd.card_count:
        raise ConflictError("No such card")
    existing = (
        await db.execute(select(TiebreakPick).where(TiebreakPick.round_id == rnd.round_id, TiebreakPick.team_id == team_id))
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("You already picked a card")
    taken = (
        await db.execute(select(TiebreakPick).where(TiebreakPick.round_id == rnd.round_id, TiebreakPick.card_index == card_index))
    ).scalar_one_or_none()
    if taken is not None:
        raise ConflictError("That card is already taken")
    p = TiebreakPick(round_id=rnd.round_id, team_id=team_id, card_index=card_index)
    db.add(p)
    await db.flush()  # the unique constraints catch a same-millisecond race
    return p


# --------------------------------------------------------------------------
# Lookups + serialisation
# --------------------------------------------------------------------------

async def get_session(db: AsyncSession, session_id: uuid.UUID) -> TiebreakSession:
    s = await db.get(TiebreakSession, session_id)
    if s is None:
        raise NotFoundError("Tiebreak not found")
    return s


async def sessions_for_round(db: AsyncSession, round_id: uuid.UUID) -> list[TiebreakSession]:
    return list(
        (
            await db.execute(
                select(TiebreakSession)
                .where(TiebreakSession.round_id == round_id, TiebreakSession.status.in_(LIVE_STATUSES))
                .order_by(TiebreakSession.created_at)
            )
        ).scalars().all()
    )


async def session_for_team(db: AsyncSession, team_id: uuid.UUID) -> TiebreakSession | None:
    return (
        await db.execute(
            select(TiebreakSession)
            .join(TiebreakParticipant, TiebreakParticipant.session_id == TiebreakSession.session_id)
            .where(TiebreakParticipant.team_id == team_id, TiebreakSession.status.in_(LIVE_STATUSES))
            .order_by(TiebreakSession.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def serialize(db: AsyncSession, session: TiebreakSession, *, for_team_id: uuid.UUID | None = None) -> dict:
    """State for a device or the console. The Joker's position is only
    included for resolved rounds."""
    room = await db.get(Room, session.room_id)
    parts = await _participants(db, session.session_id)
    teams = {
        t.team_id: t
        for t in (await db.execute(select(Team).where(Team.team_id.in_([p.team_id for p in parts])))).scalars().all()
    }
    suits = {
        row[0]: row[1]
        for row in (
            await db.execute(
                text("""
                    SELECT rs.team_id, st.code
                      FROM round1_selections rs
                      JOIN suits st ON st.suit_id = rs.suit_id
                     WHERE rs.room_id = :room_id
                """),
                {"room_id": str(session.room_id)},
            )
        ).all()
    }
    code_of = {tid: (teams[tid].team_code if tid in teams else str(tid)) for tid in teams}

    rounds = list(
        (
            await db.execute(
                select(TiebreakRound).where(TiebreakRound.session_id == session.session_id).order_by(TiebreakRound.round_number)
            )
        ).scalars().all()
    )
    picks_by_round: dict[uuid.UUID, list[TiebreakPick]] = {}
    if rounds:
        for p in (
            await db.execute(select(TiebreakPick).where(TiebreakPick.round_id.in_([r.round_id for r in rounds])))
        ).scalars().all():
            picks_by_round.setdefault(p.round_id, []).append(p)

    def round_out(r: TiebreakRound) -> dict:
        return {
            "round_number": r.round_number,
            "card_count": r.card_count,
            "start_time": r.start_time.isoformat(),
            "deadline": r.deadline.isoformat(),
            "is_resolved": r.is_resolved,
            "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
            "joker_index": r.joker_index if r.is_resolved else None,
            "eliminated_team_code": code_of.get(r.eliminated_team_id) if r.eliminated_team_id else None,
            "picks": [
                {"team_code": code_of.get(p.team_id, "?"), "card_index": p.card_index, "auto_assigned": p.auto_assigned}
                for p in sorted(picks_by_round.get(r.round_id, []), key=lambda p: p.card_index)
            ],
        }

    current = rounds[-1] if rounds else None
    out = {
        "session_id": str(session.session_id),
        "room_id": str(session.room_id),
        "room_code": room.room_code if room else None,
        "status": session.status,
        "slots": session.slots,
        "tie_rank": session.tie_rank,
        "tie_total": float(session.tie_total),
        "round_seconds": ROUND_SECONDS,
        "reveal_seconds": REVEAL_SECONDS,
        "server_time": _now().isoformat(),
        "participants": [
            {
                "team_id": str(p.team_id),
                "team_code": code_of.get(p.team_id, "?"),
                "team_name": teams[p.team_id].team_name if p.team_id in teams else None,
                "suit_code": suits.get(p.team_id),
                "status": p.status,
                "eliminated_in_round": p.eliminated_in_round,
            }
            for p in sorted(parts, key=lambda p: code_of.get(p.team_id, ""))
        ],
        "current_round": round_out(current) if current else None,
        "rounds": [round_out(r) for r in rounds if r.is_resolved],
        "winner_team_codes": [code_of.get(p.team_id) for p in parts if p.status == WINNER],
    }
    if for_team_id is not None:
        me = next((p for p in parts if p.team_id == for_team_id), None)
        my_pick = None
        if current is not None:
            mine = next((p for p in picks_by_round.get(current.round_id, []) if p.team_id == for_team_id), None)
            my_pick = mine.card_index if mine else None
        out["my_team_code"] = code_of.get(for_team_id)
        out["my_status"] = me.status if me else None
        out["my_pick"] = my_pick
    return out
