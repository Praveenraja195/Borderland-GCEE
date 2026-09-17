import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.jack_heart import JackHeartAnswer, JackHeartAssignment, JackHeartRound, JHSymbol
from app.models.team import Team
from app.services.game_auth import authorize_game_submission

# Points for correctly naming your own hidden card. Kept as a module
# constant so the demo/practice surface (app/services/demo_service.py)
# scores a practice sub-round with the same rule without touching the DB.
CORRECT_POINTS = 10.0
WRONG_POINTS = 0.0


def compute_round_score(submitted_symbol_id: int, actual_symbol_id: int) -> float:
    return CORRECT_POINTS if submitted_symbol_id == actual_symbol_id else WRONG_POINTS


async def submit_answer(
    db: AsyncSession,
    *,
    round_id: uuid.UUID,
    team_id: uuid.UUID,
    submitted_symbol_id: int,
) -> JackHeartAnswer:
    round_obj = await db.get(JackHeartRound, round_id)
    if round_obj is None:
        raise NotFoundError("Jack of Hearts round not found")

    # Fix §4: shared auth helper replaces the copy-pasted deadline/pause/room
    # check that previously lived here and in mindmaze_service/king_diamond_service.
    await authorize_game_submission(db, round_obj=round_obj, team_id=team_id)

    # Check if an answer row already exists for this team + round (allows auto-saving selection changes)
    existing_answer = (
        await db.execute(
            select(JackHeartAnswer).where(
                JackHeartAnswer.round_id == round_id,
                JackHeartAnswer.team_id == team_id,
            )
        )
    ).scalar_one_or_none()

    # Always fetch current assignment to ensure validation uses current cards even after restarts
    assignment = (
        await db.execute(
            select(JackHeartAssignment).where(
                JackHeartAssignment.round_id == round_id,
                JackHeartAssignment.team_id == team_id,
            )
        )
    ).scalar_one_or_none()

    if assignment is None:
        raise NotFoundError("No symbol assignment found for your team in this round")

    actual_id = assignment.symbol_id
    score = compute_round_score(submitted_symbol_id, actual_id)

    if existing_answer is not None:
        existing_answer.submitted_symbol_id = submitted_symbol_id
        existing_answer.actual_symbol_id = actual_id
        existing_answer.round_score = score
        answer = existing_answer
    else:
        answer = JackHeartAnswer(
            round_id=round_id,
            team_id=team_id,
            submitted_symbol_id=submitted_symbol_id,
            actual_symbol_id=actual_id,
            round_score=score,
        )
        db.add(answer)

    await db.flush()
    await db.commit()
    await db.refresh(answer)
    return answer


async def get_visible_symbols(
    db: AsyncSession, *, round_id: uuid.UUID, current_team_id: uuid.UUID
) -> list[dict]:
    """Every *other* team's symbol for this round — never the caller's own.

    This filter is entirely the API's responsibility; nothing in the schema
    hides it automatically. See tests/test_jack_heart.py for the dedicated
    regression test asserting the caller's own symbol never appears.
    """
    round_obj = await db.get(JackHeartRound, round_id)
    if round_obj is None:
        raise NotFoundError("Jack of Hearts round not found")

    from app.models.game import GameSession
    from app.models.selection import Round1Selection, Suit

    stmt = (
        select(
            Team.team_id,
            Team.team_code,
            Team.team_name,
            Suit.code.label("team_suit_code"),
            Suit.symbol.label("team_suit_symbol"),
            JHSymbol.symbol_id,
            JHSymbol.code.label("symbol_code"),
            JHSymbol.label.label("symbol_label"),
            JHSymbol.suit.label("card_suit"),
            JHSymbol.rank.label("card_rank"),
        )
        .join(JackHeartAssignment, JackHeartAssignment.team_id == Team.team_id)
        .join(JHSymbol, JHSymbol.symbol_id == JackHeartAssignment.symbol_id)
        .join(JackHeartRound, JackHeartRound.round_id == JackHeartAssignment.round_id)
        .join(GameSession, GameSession.session_id == JackHeartRound.session_id)
        .outerjoin(
            Round1Selection,
            (Round1Selection.team_id == Team.team_id) & (Round1Selection.round_id == GameSession.round_id),
        )
        .outerjoin(Suit, Suit.suit_id == Round1Selection.suit_id)
        .where(
            JackHeartAssignment.round_id == round_id,
            JackHeartAssignment.team_id != current_team_id,
        )
    )
    rows = (await db.execute(stmt)).all()
    suit_symbol_map = {"HEART": "♥", "SPADE": "♠", "CLUB": "♣", "DIAMOND": "♦"}
    return [
        {
            "team_id": row.team_id,
            "team_code": row.team_code,
            "team_name": row.team_name,
            "team_suit_code": row.team_suit_code or row.card_suit,
            "team_suit_symbol": row.team_suit_symbol or suit_symbol_map.get(row.card_suit),
            "symbol_id": row.symbol_id,
            "symbol_code": row.symbol_code,
            "symbol_label": row.symbol_label,
            "suit": row.card_suit,
            "rank": row.card_rank,
        }
        for row in rows
    ]


async def get_all_symbols(db: AsyncSession) -> list[JHSymbol]:
    """Return all available playing card symbols ordered by symbol_id."""
    stmt = select(JHSymbol).order_by(JHSymbol.symbol_id)
    return (await db.execute(stmt)).scalars().all()


async def get_room_leaderboard(
    db: AsyncSession,
    *,
    room_id: uuid.UUID,
    current_team_id: uuid.UUID,
) -> list[dict]:
    from datetime import datetime, timezone
    from app.models.game import Game, GameSession
    from app.models.selection import Round1Selection, Suit

    game = (await db.execute(select(Game).where(Game.code == "JACK_HEART"))).scalar_one_or_none()
    if game is None:
        raise NotFoundError("Jack of Hearts game not found")

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
                select(JackHeartRound)
                .where(JackHeartRound.session_id == session.session_id)
                .order_by(JackHeartRound.round_number)
            )
        )
        .scalars()
        .all()
    )
    if not rounds:
        return []

    teams_stmt = (
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
    )
    teams = (await db.execute(teams_stmt)).all()

    # Get all answers for these rounds
    round_ids = [r.round_id for r in rounds]
    answers = (
        await db.execute(
            select(JackHeartAnswer).where(JackHeartAnswer.round_id.in_(round_ids))
        )
    ).scalars().all()

    # Map by (round_id, team_id) -> answer
    ans_map = {(a.round_id, a.team_id): a for a in answers}

    now = datetime.now(timezone.utc)
    results = []
    for t in teams:
        subrounds = []
        total_score = 0.0
        for r in rounds:
            ans = ans_map.get((r.round_id, t.team_id))
            is_closed = getattr(r, "is_closed", False) or (r.deadline is not None and r.deadline <= now)
            score = float(ans.round_score) if ans and ans.round_score is not None else 0.0
            is_correct = bool(ans.is_correct) if ans else False

            subrounds.append({
                "round_number": r.round_number,
                "is_closed": is_closed,
                "is_correct": is_correct if is_closed else None,
                "score": score if is_closed else 0.0,
            })
            if is_closed:
                total_score += score

        results.append({
            "team_id": t.team_id,
            "team_code": t.team_code,
            "team_name": t.team_name,
            "team_suit_code": t.team_suit_code,
            "team_suit_symbol": t.team_suit_symbol,
            "is_current_team": (t.team_id == current_team_id),
            "subrounds": subrounds,
            "total_score": round(total_score, 1),
        })

    # Sort by total_score DESC, team_code ASC
    results.sort(key=lambda x: (-x["total_score"], x["team_code"]))
    for rank, entry in enumerate(results, start=1):
        entry["rank"] = rank

    return results


async def get_team_suit_info(
    db: AsyncSession, *, round_id: uuid.UUID, team_id: uuid.UUID
) -> dict:
    round_obj = await db.get(JackHeartRound, round_id)
    if round_obj is None:
        raise NotFoundError("Jack of Hearts round not found")

    from app.models.game import GameSession
    from app.models.selection import Round1Selection, Suit

    suit_code = None
    suit_symbol = None

    # Source 1: Check Round1Selection for this team in this game's session round
    session = await db.get(GameSession, round_obj.session_id)
    if session:
        sel_stmt = (
            select(Suit.code, Suit.symbol)
            .join(Round1Selection, Round1Selection.suit_id == Suit.suit_id)
            .where(
                Round1Selection.team_id == team_id,
                Round1Selection.round_id == session.round_id,
            )
        )
        suit_row = (await db.execute(sel_stmt)).first()
        if suit_row:
            suit_code = suit_row[0].upper() if suit_row[0] else None
            suit_symbol = suit_row[1] if suit_row[1] else None

    # Source 2: General Round1Selection for this team
    if not suit_code:
        sel_stmt = (
            select(Suit.code, Suit.symbol)
            .join(Round1Selection, Round1Selection.suit_id == Suit.suit_id)
            .where(Round1Selection.team_id == team_id)
            .order_by(Round1Selection.selected_at.desc())
        )
        suit_row = (await db.execute(sel_stmt)).first()
        if suit_row:
            suit_code = suit_row[0].upper() if suit_row[0] else None
            suit_symbol = suit_row[1] if suit_row[1] else None

    # Source 3: Check JackHeartAssignment for this team in this round
    if not suit_code:
        assign_stmt = (
            select(JHSymbol.suit)
            .join(JackHeartAssignment, JackHeartAssignment.symbol_id == JHSymbol.symbol_id)
            .where(
                JackHeartAssignment.round_id == round_id,
                JackHeartAssignment.team_id == team_id,
            )
        )
        assigned_suit = (await db.execute(assign_stmt)).scalar_one_or_none()
        if assigned_suit:
            suit_code = assigned_suit.upper()

    suit_symbol_map = {"HEART": "♥", "SPADE": "♠", "CLUB": "♣", "DIAMOND": "♦"}
    if suit_code and not suit_symbol:
        suit_symbol = suit_symbol_map.get(suit_code)

    symbols_stmt = select(JHSymbol)
    if suit_code:
        symbols_stmt = symbols_stmt.where(JHSymbol.suit == suit_code)
    symbols_stmt = symbols_stmt.order_by(JHSymbol.symbol_id)
    symbols = (await db.execute(symbols_stmt)).scalars().all()

    return {
        "suit_code": suit_code,
        "suit_symbol": suit_symbol,
        "symbols": [
            {
                "symbol_id": s.symbol_id,
                "code": s.code,
                "label": s.label,
                "suit": s.suit,
                "rank": s.rank,
            }
            for s in symbols
        ],
    }


