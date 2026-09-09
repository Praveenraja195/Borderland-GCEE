import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models.ace_spade import AceSpadeResult, AceSpadeRound
from app.models.game import Game, GameScore, GameSession
from app.models.selection import Round1Selection
from app.models.team import Team
from app.services.game_auth import authorize_game_submission


def compute_round_score(correct_picks: int, wrong_picks: int) -> float:
    """One Ace of Spades sub-round's score: +2.0 per card recalled in the
    correct memorised position, -0.5 per wrong pick (including a decoy
    card), floored at 0.

    Extracted as a pure function so the demo/practice surface
    (app/services/demo_service.py) scores a practice sub-round with the
    exact same rule as a real one without going anywhere near the DB.
    """
    return max(0.0, float((correct_picks * 2.0) - (wrong_picks * 0.5)))


async def submit_result(
    db: AsyncSession,
    *,
    round_id: uuid.UUID,
    team_id: uuid.UUID,
    moves: int,
    wrong_picks: int,
    correct_picks: int,
    completion_time_seconds: float | None,
) -> AceSpadeResult:
    round_obj = await db.get(AceSpadeRound, round_id)
    if round_obj is None:
        raise NotFoundError("Ace of Spades round not found")

    # A stale frontend reload could otherwise replay an already-submitted
    # (but not-yet-closed) sub-round and fire a second submit at it — same
    # defensive pre-check mindmaze_service.submit_result uses.
    existing = (
        await db.execute(
            select(AceSpadeResult).where(
                AceSpadeResult.round_id == round_id, AceSpadeResult.team_id == team_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    # Server-side bounds on client-supplied gameplay metrics: only 8 cards
    # are ever memorised in one sub-round, so correct_picks can never
    # legitimately exceed that.
    max_cards = settings.ace_spade_max_cards
    if correct_picks < 0 or correct_picks > max_cards:
        raise ConflictError(
            f"correct_picks must be between 0 and the number of memorised cards ({max_cards}). "
            f"Received: {correct_picks}"
        )
    wrong_picks = max(0, int(wrong_picks))
    moves = max(moves, correct_picks + wrong_picks, correct_picks)
    if completion_time_seconds is not None:
        valid_time = max(0.0, float(completion_time_seconds))
    else:
        valid_time = None

    await authorize_game_submission(db, round_obj=round_obj, team_id=team_id, check_deadline=False)

    score = compute_round_score(correct_picks, wrong_picks)
    result = AceSpadeResult(
        round_id=round_id,
        team_id=team_id,
        moves=moves,
        wrong_picks=wrong_picks,
        correct_picks=correct_picks,
        round_score=score,
        completion_time=timedelta(seconds=valid_time) if valid_time is not None else None,
    )

    db.add(result)
    await db.flush()

    # Update running GameScore for this session so mid-game scores are tracked
    running_total = (
        await db.execute(
            select(func.coalesce(func.sum(AceSpadeResult.round_score), 0.0))
            .select_from(AceSpadeResult)
            .join(AceSpadeRound, AceSpadeRound.round_id == AceSpadeResult.round_id)
            .where(AceSpadeRound.session_id == round_obj.session_id, AceSpadeResult.team_id == team_id)
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
    current_team_id: uuid.UUID | None = None,
) -> list:
    from app.models.selection import Round1Selection, Suit
    from app.schemas.ace_spade import AceSpadeRoomLeaderboardEntry, AceSpadeSubroundScore

    game = (await db.execute(select(Game).where(Game.code == "ACE_SPADE"))).scalar_one_or_none()
    if game is None:
        raise NotFoundError("Ace of Spades game not found")

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
                select(AceSpadeRound)
                .where(AceSpadeRound.session_id == session.session_id)
                .order_by(AceSpadeRound.round_number)
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
                select(AceSpadeResult).where(AceSpadeResult.round_id.in_(round_ids))
            )
        )
        .scalars()
        .all()
    )

    results_by_team: dict[uuid.UUID, dict[int, AceSpadeResult]] = {}
    for res in results:
        r_num = round_by_id.get(res.round_id)
        if r_num:
            results_by_team.setdefault(res.team_id, {})[r_num] = res

    entries = []
    for t in teams:
        subrounds = []
        total_score = 0.0
        total_correct = 0
        team_res_map = results_by_team.get(t.team_id, {})

        for r in rounds:
            res = team_res_map.get(r.round_number)
            if res:
                s_score = float(res.round_score or 0)
                total_score += s_score
                total_correct += (res.correct_picks or 0)
                subrounds.append(
                    AceSpadeSubroundScore(
                        round_number=r.round_number,
                        score=s_score,
                        correct_picks=res.correct_picks,
                        wrong_picks=res.wrong_picks,
                        submitted=True,
                    )
                )
            else:
                subrounds.append(
                    AceSpadeSubroundScore(
                        round_number=r.round_number,
                        score=0.0,
                        correct_picks=None,
                        wrong_picks=None,
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

    entries.sort(key=lambda e: (-e["total_score"], -e["total_correct"], e["team_code"]))

    ranked_entries = []
    for idx, e in enumerate(entries):
        ranked_entries.append(
            AceSpadeRoomLeaderboardEntry(
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
