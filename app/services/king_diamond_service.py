import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.game import GameSession
from app.models.king_diamond import KingDiamondRound, KingDiamondSubmission
from app.models.selection import Round1Selection
from app.models.team import Team
from app.services.game_auth import authorize_game_submission

# Scoring: Every team starts the game with 100.0 points total across all 5 rounds (20.0 per round).
# Each sub-round deducts penalties based on nearness rank:
#   Rank 1 (nearest): -0 deduction (keeps full 20 for that round)
#   Rank 2:           -1.0 deduction (20 - 1 = 19 for that round)
#   Rank 3:           -2.5 deduction (20 - 2.5 = 17.5 for that round)
#   Rank 4:           -4.5 deduction (20 - 4.5 = 15.5 for that round)
#   Rank r:           0.25*(r-1)*(r+2) deduction
#   Non-submitter:    -20.0 deduction (full penalty for that round)
# Total score at any time is max(0, 100.0 - sum(penalties across all 5 rounds)).
BASE_POINTS = settings.king_diamond_base_points  # 20


def _penalty_for_rank(rank: int) -> float:
    """Progressive penalty for a 1-indexed nearness rank.
    Step k (from rank k to k+1) costs (0.5 + 0.5*k) points.
    Cumulative: penalty(r) = 0.25 * (r-1) * (r+2)
    """
    if rank <= 1:
        return 0.0
    return 0.25 * (rank - 1) * (rank + 2)


def _round_score_for_rank(rank: int | None) -> float:
    """Penalty points deducted for this sub-round.
    Rank 1 = 0.0, Rank 2 = 1.0, Rank 3 = 2.5, Rank 4 = 4.5...
    Unranked / invalid / non-submitter = 20.0 (full penalty for that round)."""
    if rank is None or rank < 1:
        return float(BASE_POINTS)
    return float(_penalty_for_rank(rank))


async def _get_room_team_ids(db: AsyncSession, session: GameSession) -> list[uuid.UUID]:
    """Returns the list of team IDs assigned to this session's room."""
    if session.roster_team_ids:
        return [uuid.UUID(t) for t in session.roster_team_ids]
    rows = (
        (
            await db.execute(
                select(Round1Selection.team_id).where(Round1Selection.room_id == session.room_id)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def _get_team_code_map(db: AsyncSession, team_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Returns a dict mapping team_id -> team_code for the given team IDs."""
    if not team_ids:
        return {}
    rows = (
        await db.execute(
            select(Team.team_id, Team.team_code).where(Team.team_id.in_(team_ids))
        )
    ).all()
    return {row.team_id: row.team_code for row in rows}


async def submit_number(
    db: AsyncSession,
    *,
    round_id: uuid.UUID,
    team_id: uuid.UUID,
    submitted_number: float,
) -> KingDiamondSubmission:
    round_obj = await db.get(KingDiamondRound, round_id)
    if round_obj is None:
        raise NotFoundError("King of Diamonds round not found")

    session_obj = await db.get(GameSession, round_obj.session_id)

    existing = (
        await db.execute(
            select(KingDiamondSubmission).where(
                KingDiamondSubmission.round_id == round_id,
                KingDiamondSubmission.team_id == team_id,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.submitted_number = submitted_number
        existing.is_valid = True
        await db.flush()
        await db.commit()
        await db.refresh(existing)
        if round_obj.is_closed:
            from app.workers.jobs import _maybe_close_session, _publish
            await close_round(db, round_id=round_id)
            if session_obj:
                await _maybe_close_session(session_obj.session_id)
                await _publish(f"room:{session_obj.room_id}:sessions")
        return existing

    await authorize_game_submission(db, round_obj=round_obj, team_id=team_id)

    submission = KingDiamondSubmission(
        round_id=round_id,
        team_id=team_id,
        submitted_number=submitted_number,
        is_valid=True,
    )
    db.add(submission)
    await db.flush()
    await db.commit()
    await db.refresh(submission)

    # Early-close: if all room teams have submitted, close immediately
    if session_obj and not round_obj.is_closed:
        room_teams = await _get_room_team_ids(db, session_obj)
        submitted_team_ids = set(
            (
                await db.execute(
                    select(KingDiamondSubmission.team_id).where(
                        KingDiamondSubmission.round_id == round_id,
                        KingDiamondSubmission.is_valid == True,
                    )
                )
            )
            .scalars()
            .all()
        )
        if room_teams and set(room_teams).issubset(submitted_team_ids):
            from app.workers.jobs import _maybe_close_session, _publish
            from app.workers.scheduler import cancel_round_close

            await close_round(db, round_id=round_id)
            await _maybe_close_session(session_obj.session_id)
            cancel_round_close("KING_DIAMOND", round_id)
            await _publish(f"room:{session_obj.room_id}:sessions")

    return submission


async def close_round(db: AsyncSession, *, round_id: uuid.UUID) -> None:
    """Runs fn_close_king_diamond_round (computes average/target/difference/rank)
    then assigns the penalty to round_score for each submission."""
    round_obj = await db.get(KingDiamondRound, round_id)
    if round_obj is None:
        raise NotFoundError("King of Diamonds round not found")

    session_obj = await db.get(GameSession, round_obj.session_id)
    if session_obj:
        room_teams = await _get_room_team_ids(db, session_obj)
        if room_teams:
            submitted_team_ids = set(
                (
                    await db.execute(
                        select(KingDiamondSubmission.team_id).where(
                            KingDiamondSubmission.round_id == round_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            missing = [t for t in room_teams if t not in submitted_team_ids]
            for missing_team_id in missing:
                db.add(
                    KingDiamondSubmission(
                        round_id=round_id,
                        team_id=missing_team_id,
                        submitted_number=0.0,
                        is_valid=False,
                        round_score=float(BASE_POINTS),
                    )
                )
            if missing:
                await db.flush()

    # SQL function computes average, target, difference, rank
    await db.execute(text("SELECT fn_close_king_diamond_round(:round_id)"), {"round_id": str(round_id)})

    # Assign penalty to round_score for each submission
    submissions = (
        (
            await db.execute(
                select(KingDiamondSubmission)
                .where(KingDiamondSubmission.round_id == round_id)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    for sub in submissions:
        sub.round_score = _round_score_for_rank(sub.rank if sub.is_valid else None)

    await db.commit()
    await db.refresh(round_obj)


async def get_team_round_result(
    db: AsyncSession,
    *,
    round_id: uuid.UUID,
    team_id: uuid.UUID,
) -> dict:
    """Team-facing computation reveal for one sub-round:
    Returns the target, average, all teams' numbers, penalty this round,
    and cumulative score remaining out of 100."""
    round_obj = await db.get(KingDiamondRound, round_id)
    if round_obj is None:
        raise NotFoundError("King of Diamonds round not found")

    session_obj = await db.get(GameSession, round_obj.session_id)
    if session_obj is None:
        raise NotFoundError("Session for this round not found")
    selection = (
        await db.execute(
            select(Round1Selection).where(
                Round1Selection.team_id == team_id,
                Round1Selection.round_id == session_obj.round_id,
            )
        )
    ).scalar_one_or_none()
    if selection is None or selection.room_id != session_obj.room_id:
        raise ForbiddenError("Your team is not assigned to this room")

    # Self-healing closure: buffer deadline by 30s to allow in-flight auto-submits to land (matches game_auth.py grace period)
    if not round_obj.is_closed:
        now = datetime.now(timezone.utc)
        from datetime import timedelta
        grace_deadline = (round_obj.deadline + timedelta(seconds=30)) if round_obj.deadline else None
        deadline_passed = grace_deadline is not None and grace_deadline <= now

        room_teams = await _get_room_team_ids(db, session_obj)
        submitted_team_ids = set(
            (
                await db.execute(
                    select(KingDiamondSubmission.team_id).where(
                        KingDiamondSubmission.round_id == round_id,
                        KingDiamondSubmission.is_valid == True,
                    )
                )
            )
            .scalars()
            .all()
        )
        all_submitted = room_teams and set(room_teams).issubset(submitted_team_ids)

        if all_submitted or deadline_passed:
            from app.workers.jobs import _maybe_close_session, _publish
            from app.workers.scheduler import cancel_round_close

            await close_round(db, round_id=round_id)
            await _maybe_close_session(session_obj.session_id)
            cancel_round_close("KING_DIAMOND", round_id)
            await _publish(f"room:{session_obj.room_id}:sessions")
            await db.refresh(round_obj)

    # Get this team's submission
    submission = (
        await db.execute(
            select(KingDiamondSubmission)
            .where(
                KingDiamondSubmission.round_id == round_id,
                KingDiamondSubmission.team_id == team_id,
            )
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()

    # Calculate cumulative points remaining out of 30 for this team
    session_subs = (
        (
            await db.execute(
                select(KingDiamondSubmission)
                .join(KingDiamondRound, KingDiamondSubmission.round_id == KingDiamondRound.round_id)
                .where(
                    KingDiamondRound.session_id == round_obj.session_id,
                    KingDiamondRound.is_closed == True,
                    KingDiamondSubmission.team_id == team_id,
                )
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    total_penalty = sum(
        float(s.round_score) if (s.round_score is not None and (float(s.round_score) > 0 or s.rank == 1))
        else _round_score_for_rank(s.rank if s.is_valid else None)
        for s in session_subs
    )
    total_rounds_res = await db.execute(
        select(func.count(KingDiamondRound.round_id)).where(
            KingDiamondRound.session_id == round_obj.session_id
        )
    )
    total_rounds = total_rounds_res.scalar() or 5
    total_base = float(total_rounds * BASE_POINTS)
    remaining_score = max(0.0, total_base - total_penalty)

    # Build all_submissions list (only when round is closed)
    all_submissions = []
    total_teams = 0
    if round_obj.is_closed:
        all_subs = (
            (
                await db.execute(
                    select(KingDiamondSubmission)
                    .where(KingDiamondSubmission.round_id == round_id)
                    .order_by(KingDiamondSubmission.rank.asc().nullslast())
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        total_teams = len(all_subs)

        sub_team_ids = [s.team_id for s in all_subs]
        team_code_map = await _get_team_code_map(db, sub_team_ids)

        for sub in all_subs:
            penalty = (
                float(sub.round_score) if (sub.round_score is not None and (float(sub.round_score) > 0 or sub.rank == 1))
                else _round_score_for_rank(sub.rank if sub.is_valid else None)
            )
            all_submissions.append({
                "team_code": team_code_map.get(sub.team_id, "???"),
                "team_id": str(sub.team_id),
                "submitted_number": float(sub.submitted_number),
                "is_valid": bool(sub.is_valid),
                "difference": float(sub.difference) if sub.difference is not None else None,
                "rank": sub.rank,
                "penalty": round(penalty, 1),
                "round_score": round(penalty, 1),
                "is_you": sub.team_id == team_id,
            })

    this_round_penalty = (
        float(submission.round_score) if (submission and submission.round_score is not None and (float(submission.round_score) > 0 or submission.rank == 1))
        else (_round_score_for_rank(submission.rank if submission.is_valid else None) if submission is not None else 0.0)
    )

    return {
        "round_id": round_obj.round_id,
        "round_number": round_obj.round_number,
        "is_closed": bool(round_obj.is_closed),
        "average_value": float(round_obj.average_value) if round_obj.average_value is not None else None,
        "target_value": float(round_obj.target_value) if round_obj.target_value is not None else None,
        "submitted_number": float(submission.submitted_number) if submission is not None else None,
        "difference": float(submission.difference) if submission is not None and submission.difference is not None else None,
        "rank": submission.rank if submission is not None else None,
        "round_score": round(remaining_score, 1),
        "penalty": round(this_round_penalty, 1),
        "base_points": BASE_POINTS,
        "total_rounds": total_rounds,
        "total_base_points": total_base,
        "is_valid": bool(submission.is_valid) if submission is not None else False,
        "total_teams": total_teams,
        "all_submissions": all_submissions,
    }


async def get_room_leaderboard(
    db: AsyncSession,
    *,
    room_id: uuid.UUID,
    current_team_id: uuid.UUID | None = None,
) -> list:
    from app.models.game import Game, GameSession
    from app.models.selection import Round1Selection, Suit
    from app.models.team import Team
    from app.schemas.king_diamond import (
        KingDiamondRoomLeaderboardEntry,
        KingDiamondSubroundScore,
    )

    game = (await db.execute(select(Game).where(Game.code == "KING_DIAMOND"))).scalar_one_or_none()
    if game is None:
        raise NotFoundError("King of Diamonds game not found")

    session = (
        await db.execute(
            select(GameSession).where(
                GameSession.room_id == room_id, GameSession.game_id == game.game_id
            )
        )
    ).scalar_one_or_none()
    if session is None:
        return []

    rounds = (
        (
            await db.execute(
                select(KingDiamondRound)
                .where(KingDiamondRound.session_id == session.session_id)
                .order_by(KingDiamondRound.round_number)
            )
        )
        .scalars()
        .all()
    )
    if not rounds:
        return []

    round_ids = [r.round_id for r in rounds]
    round_by_id = {r.round_id: r.round_number for r in rounds}

    teams = (
        await db.execute(
            select(
                Team.team_id,
                Team.team_code,
                Team.team_name,
                Suit.code.label("team_suit_code"),
                Suit.symbol.label("team_suit_symbol"),
            )
            .join(Round1Selection, Round1Selection.team_id == Team.team_id)
            .outerjoin(Suit, Suit.suit_id == Round1Selection.suit_id)
            .where(Round1Selection.room_id == room_id)
            .order_by(Team.team_code)
        )
    ).all()

    submissions = (
        (
            await db.execute(
                select(KingDiamondSubmission).where(KingDiamondSubmission.round_id.in_(round_ids))
            )
        )
        .scalars()
        .all()
    )

    subs_by_team: dict[uuid.UUID, dict[int, KingDiamondSubmission]] = {}
    for sub in submissions:
        r_num = round_by_id.get(sub.round_id)
        if r_num:
            subs_by_team.setdefault(sub.team_id, {})[r_num] = sub

    entries = []
    for t in teams:
        subrounds = []
        total_penalty = 0.0
        team_subs = subs_by_team.get(t.team_id, {})

        for r in rounds:
            sub = team_subs.get(r.round_number)
            if sub and r.is_closed:
                penalty = float(sub.round_score or 0)
                total_penalty += penalty
                subrounds.append(
                    KingDiamondSubroundScore(
                        round_number=r.round_number,
                        score=penalty,
                        submitted_number=float(sub.submitted_number) if sub.submitted_number is not None else None,
                        rank=sub.rank,
                        difference=float(sub.difference) if sub.difference is not None else None,
                        submitted=True,
                    )
                )
            elif sub:
                subrounds.append(
                    KingDiamondSubroundScore(
                        round_number=r.round_number,
                        score=0.0,
                        submitted_number=float(sub.submitted_number) if sub.submitted_number is not None else None,
                        rank=None,
                        difference=None,
                        submitted=True,
                    )
                )
            else:
                subrounds.append(
                    KingDiamondSubroundScore(
                        round_number=r.round_number,
                        score=0.0,
                        submitted_number=None,
                        rank=None,
                        difference=None,
                        submitted=False,
                    )
                )

        total_base = float(len(rounds) * BASE_POINTS)
        remaining_score = max(0.0, total_base - total_penalty)
        entries.append({
            "team_id": t.team_id,
            "team_code": t.team_code,
            "team_name": t.team_name,
            "team_suit_code": t.team_suit_code,
            "team_suit_symbol": t.team_suit_symbol,
            "subrounds": subrounds,
            "total_score": remaining_score,
            "is_current_team": (t.team_id == current_team_id),
        })

    # Rank by total score descending, then team code ascending
    entries.sort(key=lambda e: (-e["total_score"], e["team_code"]))

    ranked_entries = []
    for idx, e in enumerate(entries):
        ranked_entries.append(
            KingDiamondRoomLeaderboardEntry(
                team_id=e["team_id"],
                team_code=e["team_code"],
                team_name=e["team_name"],
                team_suit_code=e["team_suit_code"],
                team_suit_symbol=e["team_suit_symbol"],
                subrounds=e["subrounds"],
                total_score=e["total_score"],
                rank=idx + 1,
                is_current_team=e["is_current_team"],
            )
        )

    return ranked_entries

