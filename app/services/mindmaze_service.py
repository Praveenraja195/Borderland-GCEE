import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models.game import Game, GameScore, GameSession
from app.models.mindmaze import MindmazeResult, MindmazeRound
from app.models.selection import Round1Selection
from app.models.team import Team
from app.services.game_auth import authorize_game_submission


def compute_round_score(correct_tiles: int, mistakes: int) -> float:
    """One MindMaze sub-round's score: +1.0 per correctly recalled tile,
    -0.5 per wrongly tapped one, floored at 0.

    Extracted as a pure function so the demo/practice surface
    (app/services/demo_service.py) scores a practice sub-round with the
    exact same rule as a real one without going anywhere near the DB.
    """
    return max(0.0, float((correct_tiles * 1.0) - (mistakes * 0.5)))


async def submit_result(
    db: AsyncSession,
    *,
    round_id: uuid.UUID,
    team_id: uuid.UUID,
    moves: int,
    mistakes: int,
    correct_tiles: int,
    completion_time_seconds: float | None,
) -> MindmazeResult:
    round_obj = await db.get(MindmazeRound, round_id)
    if round_obj is None:
        raise NotFoundError("MindMaze round not found")

    # Bug-fix batch (Aug 2026): explicit pre-check instead of relying solely
    # on the mindmaze_results_round_id_team_id_key UNIQUE constraint /
    # IntegrityError translation. A stale frontend reload used to be able
    # to replay an already-submitted (but not-yet-closed) sub-round and
    # fire a second submit at it; that still gets rejected here, cleanly
    # and before any of the metric-bounds work below, with the same
    # message the constraint-violation path produces.
    existing = (
        await db.execute(
            select(MindmazeResult).where(
                MindmazeResult.round_id == round_id, MindmazeResult.team_id == team_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    # Fix §1.1: server-side bounds on client-supplied gameplay metrics.
    # The DB schema only has CHECK (... >= 0) which allows arbitrarily large
    max_tiles = settings.mindmaze_max_tiles
    if correct_tiles < 0 or correct_tiles > max_tiles:
        raise ConflictError(
            f"correct_tiles must be between 0 and the board size ({max_tiles}). "
            f"Received: {correct_tiles}"
        )
    mistakes = max(0, int(mistakes))
    moves = max(int(moves), correct_tiles + mistakes, correct_tiles)
    if completion_time_seconds is not None:
        valid_time = max(0.0, float(completion_time_seconds))
    else:
        valid_time = None

    # Fix §4: shared auth helper replaces the copy-pasted block.
    await authorize_game_submission(db, round_obj=round_obj, team_id=team_id, check_deadline=False)

    score = compute_round_score(correct_tiles, mistakes)
    result = MindmazeResult(
        round_id=round_id,
        team_id=team_id,
        moves=moves,
        mistakes=mistakes,
        correct_tiles=correct_tiles,
        round_score=score,
        completion_time=timedelta(seconds=valid_time) if valid_time is not None else None,
    )

    db.add(result)
    await db.flush()

    # Update running GameScore for this session so mid-game scores are tracked
    running_total = (
        await db.execute(
            select(func.coalesce(func.sum(MindmazeResult.round_score), 0.0))
            .select_from(MindmazeResult)
            .join(MindmazeRound, MindmazeRound.round_id == MindmazeResult.round_id)
            .where(MindmazeRound.session_id == round_obj.session_id, MindmazeResult.team_id == team_id)
        )
    ).scalar_one()

    existing_gs = (
        await db.execute(
            select(GameScore).where(
                GameScore.session_id == round_obj.session_id, GameScore.team_id == team_id
            )
        )
    ).scalar_one_or_none()
    if existing_gs:
        existing_gs.score = float(running_total)
    else:
        db.add(
            GameScore(
                session_id=round_obj.session_id,
                team_id=team_id,
                score=float(running_total),
                completed=False,
            )
        )

    await db.flush()

    # Also update room_results for this room so main leaderboards update immediately
    session_obj = await db.get(GameSession, round_obj.session_id)
    if session_obj and session_obj.room_id:
        try:
            await db.execute(
                text("SELECT fn_compute_room_results(:room_id)"),
                {"room_id": str(session_obj.room_id)},
            )
        except Exception:
            pass

    await db.commit()
    await db.refresh(result)
    return result


async def get_room_leaderboard(
    db: AsyncSession,
    *,
    room_id: uuid.UUID,
    current_team_id: uuid.UUID,
) -> list:
    from app.models.game import Game, GameSession
    from app.models.selection import Round1Selection, Suit
    from app.models.team import Team
    from app.schemas.mindmaze import MindmazeRoomLeaderboardEntry, MindmazeSubroundScore

    game = (await db.execute(select(Game).where(Game.code == "MINDMAZE"))).scalar_one_or_none()
    if game is None:
        raise NotFoundError("MindMaze game not found")

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
                select(MindmazeRound)
                .where(MindmazeRound.session_id == session.session_id)
                .order_by(MindmazeRound.round_number)
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

    results = (
        (
            await db.execute(
                select(MindmazeResult).where(MindmazeResult.round_id.in_(round_ids))
            )
        )
        .scalars()
        .all()
    )

    results_by_team: dict[uuid.UUID, dict[int, MindmazeResult]] = {}
    for res in results:
        r_num = round_by_id.get(res.round_id)
        if r_num:
            results_by_team.setdefault(res.team_id, {})[r_num] = res

    entries = []
    for t in teams:
        subrounds = []
        total_score = 0.0
        total_correct = 0
        total_mistakes = 0
        team_res_map = results_by_team.get(t.team_id, {})

        for r in rounds:
            res = team_res_map.get(r.round_number)
            if res:
                s_score = float(res.round_score or 0)
                total_score += s_score
                total_correct += (res.correct_tiles or 0)
                total_mistakes += (res.mistakes or 0)
                subrounds.append(
                    MindmazeSubroundScore(
                        round_number=r.round_number,
                        score=s_score,
                        correct_tiles=res.correct_tiles,
                        mistakes=res.mistakes,
                        submitted=True,
                    )
                )
            else:
                subrounds.append(
                    MindmazeSubroundScore(
                        round_number=r.round_number,
                        score=0.0,
                        correct_tiles=None,
                        mistakes=None,
                        submitted=False,
                    )
                )

        entries.append({
            "team_id": t.team_id,
            "team_code": t.team_code,
            "team_name": t.team_name,
            "team_suit_code": t.team_suit_code,
            "team_suit_symbol": t.team_suit_symbol,
            "subrounds": subrounds,
            "total_score": total_score,
            "total_correct": total_correct,
            "is_current_team": (t.team_id == current_team_id),
        })

    # Rank by total score descending, then total correct descending, then team code ascending
    entries.sort(key=lambda e: (-e["total_score"], -e["total_correct"], e["team_code"]))

    ranked_entries = []
    for idx, e in enumerate(entries):
        ranked_entries.append(
            MindmazeRoomLeaderboardEntry(
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
