"""
Business logic backing the admin-only endpoints (Part 2 of the audit's
design doc) that doesn't already live in a game-specific service module.
Keeps app/api/v1/*.py routers thin, matching the rest of this codebase.
"""

import uuid

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import hash_password
from app.models.admin import Admin
from app.models.game import Game, GameSession, RoundGames, SessionStatus
from app.models.round import Round, RoundStatus, Room
from app.models.selection import Round1Selection
from app.models.team import Team
from app.schemas.round import GameLineupEntry, GameLineupOut
from app.schemas.team import TeamAdminDetailOut, TeamAdminListEntry

# ---------------------------------------------------------------------------
# §2.1 Team Management
# ---------------------------------------------------------------------------


async def create_team(db: AsyncSession, *, team_code: str, team_name: str, password: str) -> Team:
    """Audit Issue 4: team creation moved here from the public, unauthenticated
    POST /teams endpoint. The 40-team cap is enforced by trg_team_cap in the
    DB; attempt the insert and let the trigger's RAISE EXCEPTION surface as a
    409 via the IntegrityError handler."""
    team = Team(team_code=team_code, team_name=team_name, password_hash=hash_password(password))
    db.add(team)
    await db.flush()
    await db.commit()
    await db.refresh(team)
    return team


async def _latest_round_id(db: AsyncSession) -> uuid.UUID | None:
    return (await db.execute(select(Round.round_id).order_by(Round.round_number.desc()).limit(1))).scalar_one_or_none()


async def list_teams(db: AsyncSession, *, round_id: uuid.UUID | None = None) -> list[TeamAdminListEntry]:
    round_id = round_id or await _latest_round_id(db)

    teams = (await db.execute(select(Team).order_by(Team.team_code))).scalars().all()
    selections_by_team: dict[uuid.UUID, Round1Selection] = {}
    if round_id is not None:
        rows = (
            (await db.execute(select(Round1Selection).where(Round1Selection.round_id == round_id))).scalars().all()
        )
        selections_by_team = {r.team_id: r for r in rows}

    from app.models.round import Room
    from app.models.selection import Suit

    rooms_by_id = {r.room_id: r for r in (await db.execute(select(Room))).scalars().all()}
    suits_by_id = {s.suit_id: s for s in (await db.execute(select(Suit))).scalars().all()}

    out = []
    for team in teams:
        selection = selections_by_team.get(team.team_id)
        room = rooms_by_id.get(selection.room_id) if selection and selection.room_id else None
        suit = suits_by_id.get(selection.suit_id) if selection else None
        out.append(
            TeamAdminListEntry(
                team_id=team.team_id,
                team_code=team.team_code,
                team_name=team.team_name,
                created_at=team.created_at,
                room_code=room.room_code if room else None,
                suit_code=suit.code if suit else None,
                has_selected=selection is not None,
                leader_name=team.leader_name,
                leader_phone=team.leader_phone,
                leader_email=team.leader_email,
            )
        )
    return out


async def get_team_detail(
    db: AsyncSession, *, team_id: uuid.UUID, round_id: uuid.UUID | None = None
) -> TeamAdminDetailOut:
    team = await db.get(Team, team_id)
    if team is None:
        raise NotFoundError("Team not found")

    round_id = round_id or await _latest_round_id(db)
    selection = None
    if round_id is not None:
        selection = (
            await db.execute(
                select(Round1Selection).where(
                    Round1Selection.round_id == round_id, Round1Selection.team_id == team_id
                )
            )
        ).scalar_one_or_none()

    room_code = None
    suit_code = None
    if selection is not None:
        from app.models.round import Room
        from app.models.selection import Suit

        if selection.room_id:
            room = await db.get(Room, selection.room_id)
            room_code = room.room_code if room else None
        suit = await db.get(Suit, selection.suit_id)
        suit_code = suit.code if suit else None

    scores = (
        await db.execute(
            text(
                "SELECT g.code AS game_code, gs.score, gs.completed "
                "FROM game_scores gs "
                "JOIN game_sessions se ON se.session_id = gs.session_id "
                "JOIN games g ON g.game_id = se.game_id "
                "WHERE gs.team_id = :team_id"
            ),
            {"team_id": str(team_id)},
        )
    ).mappings().all()

    return TeamAdminDetailOut(
        team_id=team.team_id,
        team_code=team.team_code,
        team_name=team.team_name,
        created_at=team.created_at,
        room_code=room_code,
        suit_code=suit_code,
        selected_number=selection.selected_number if selection else None,
        has_selected=selection is not None,
        game_scores=[dict(row) for row in scores],
        leader_name=team.leader_name,
        leader_phone=team.leader_phone,
        leader_email=team.leader_email,
    )


async def reset_team_password(db: AsyncSession, *, team_id: uuid.UUID, new_password: str) -> Team:
    team = await db.get(Team, team_id)
    if team is None:
        raise NotFoundError("Team not found")
    team.password_hash = hash_password(new_password)
    await db.commit()
    await db.refresh(team)
    return team


async def delete_team(db: AsyncSession, *, team_id: uuid.UUID) -> None:
    team = await db.get(Team, team_id)
    if team is None:
        raise NotFoundError("Team not found")

    active_round = (
        await db.execute(
            select(Round1Selection.selection_id)
            .join(Round, Round.round_id == Round1Selection.round_id)
            .where(Round1Selection.team_id == team_id, Round.status != RoundStatus.NOT_STARTED)
        )
    ).scalar_one_or_none()
    if active_round is not None:
        raise ConflictError("Cannot remove a team once its round has gone ACTIVE")

    await db.delete(team)
    await db.commit()


# ---------------------------------------------------------------------------
# §2.2 Room Assignment Override (Move a Team)
# ---------------------------------------------------------------------------


async def _room_has_started_session(db: AsyncSession, room_id: uuid.UUID) -> bool:
    """Only block team moves when a game session in this room is genuinely
    running or finished — NOT_STARTED sessions don't count."""
    _STARTED_STATUSES = {SessionStatus.IN_PROGRESS, SessionStatus.PAUSED, SessionStatus.COMPLETED}
    sessions = (await db.execute(select(GameSession).where(GameSession.room_id == room_id))).scalars().all()
    return any(s.status in _STARTED_STATUSES for s in sessions)


async def _find_available_suit(db: AsyncSession, round_id: uuid.UUID, target_number: int, current_suit_id: int | None = None) -> int:
    from app.models.selection import Suit
    all_suits = (await db.execute(select(Suit))).scalars().all()
    if not all_suits:
        raise NotFoundError("No suits configured in DB")

    taken_suits = (
        await db.execute(
            select(Round1Selection.suit_id)
            .join(Room, Room.room_id == Round1Selection.room_id)
            .where(Room.round_id == round_id, Room.room_number == target_number)
        )
    ).scalars().all()
    taken_set = set(taken_suits)

    if current_suit_id is not None and current_suit_id not in taken_set:
        return current_suit_id

    for suit in all_suits:
        if suit.suit_id not in taken_set:
            return suit.suit_id

    return all_suits[len(taken_suits) % len(all_suits)].suit_id


async def move_team_room(
    db: AsyncSession, *, round_id: uuid.UUID, team_id: uuid.UUID, target_number: int
) -> Round1Selection:
    selection = (
        await db.execute(
            select(Round1Selection).where(
                Round1Selection.round_id == round_id, Round1Selection.team_id == team_id
            )
        )
    ).scalar_one_or_none()

    target_room = (
        await db.execute(select(Room).where(Room.round_id == round_id, Room.room_number == target_number))
    ).scalar_one_or_none()
    if target_room is None:
        raise NotFoundError(f"Room number {target_number} not found in this round")

    if await _room_has_started_session(db, target_room.room_id):
        raise ConflictError("Cannot move a team into a room once a game session there has started")

    if selection is not None:
        old_room_id = selection.room_id
        if old_room_id and await _room_has_started_session(db, old_room_id):
            raise ConflictError("Cannot move a team once a game session in its current room has started")

        suit_id = await _find_available_suit(db, round_id, target_number, selection.suit_id)

        # trg_lock_selection only blocks UPDATE, not DELETE — this is the
        # sanctioned admin-only bypass path described in the design doc.
        await db.delete(selection)
        await db.flush()
    else:
        old_room_id = None
        suit_id = await _find_available_suit(db, round_id, target_number)

    new_selection = Round1Selection(
        round_id=round_id, team_id=team_id, suit_id=suit_id, selected_number=target_number
    )
    db.add(new_selection)
    # flush so trg_assign_room / uq_suit_number_per_round fire here, inside
    # this request's transaction, and any IntegrityError surfaces cleanly.
    await db.flush()
    await db.commit()
    await db.refresh(new_selection)

    if old_room_id:
        await db.execute(text("SELECT fn_compute_room_results(:room_id)"), {"room_id": str(old_room_id)})
    if new_selection.room_id:
        await db.execute(text("SELECT fn_compute_room_results(:room_id)"), {"room_id": str(new_selection.room_id)})
    await db.commit()

    return new_selection


async def delete_team_selection(db: AsyncSession, *, round_id: uuid.UUID, team_id: uuid.UUID) -> None:
    selection = (
        await db.execute(
            select(Round1Selection).where(
                Round1Selection.round_id == round_id, Round1Selection.team_id == team_id
            )
        )
    ).scalar_one_or_none()
    if selection is None:
        raise NotFoundError("No selection found for this team in this round")

    if selection.room_id:
        if await _room_has_started_session(db, selection.room_id):
            raise ConflictError("Cannot unassign a team once a game session in its room has started")

    await db.delete(selection)
    await db.commit()


# ---------------------------------------------------------------------------
# §2.4 Game Lineup per Round
# ---------------------------------------------------------------------------

# Audit §2.2: the results schema (room_results, v_room_leaderboard,
# v_overall_leaderboard in sql/round1_schema.sql) hardcodes exactly these
# three games. replace_game_lineup enforces that the configurable lineup
# stays a subset of this set rather than silently accepting a game the
# leaderboard pipeline can't score.
_KNOWN_GAME_CODES = {"MINDMAZE", "ACE_SPADE", "KING_DIAMOND", "JACK_HEART"}


async def replace_game_lineup(
    db: AsyncSession, *, round_id: uuid.UUID, entries: list[GameLineupEntry]
) -> list[GameLineupOut]:
    round_obj = await db.get(Round, round_id)
    if round_obj is None:
        raise NotFoundError("Round not found")

    sessions = (await db.execute(select(GameSession).where(GameSession.round_id == round_id))).scalars().all()
    if any(s.status != SessionStatus.NOT_STARTED for s in sessions):
        raise ConflictError("Cannot change the game lineup once a session in this round has started")

    await db.execute(delete(RoundGames).where(RoundGames.round_id == round_id))
    await db.flush()

    out: list[GameLineupOut] = []
    for entry in entries:
        game_code = entry.game_code.upper()
        # Audit §2.2: room_results / v_room_leaderboard / v_overall_leaderboard
        # in sql/round1_schema.sql have fixed mindmaze_score/king_diamond_score
        # /jack_heart_score columns — the results pipeline is wired for
        # exactly these three games, not an arbitrary lineup. This endpoint
        # configures which *subset* of the three runs in a round; it can't
        # safely accept a 4th game without a schema change (a generic,
        # game_scores-driven leaderboard or dynamic pivot), so reject
        # anything outside the known set here rather than let it silently
        # never appear in room_results/the leaderboard views later.
        if game_code not in _KNOWN_GAME_CODES:
            raise ConflictError(
                f"'{entry.game_code}' isn't one of the three games the results schema supports "
                f"({', '.join(sorted(_KNOWN_GAME_CODES))}). See design notes in README.md."
            )
        game = (await db.execute(select(Game).where(Game.code == game_code))).scalar_one_or_none()
        if game is None:
            raise NotFoundError(f"Unknown game_code '{entry.game_code}'")
        db.add(RoundGames(round_id=round_id, game_id=game.game_id, game_order=entry.game_order))
        out.append(
            GameLineupOut(
                game_code=game.code, game_order=entry.game_order, game_id=game.game_id, game_name=game.name
            )
        )

    await db.commit()
    out.sort(key=lambda e: e.game_order)
    return out


async def remove_round_game(db: AsyncSession, *, round_id: uuid.UUID, game_code: str) -> None:
    game = (await db.execute(select(Game).where(Game.code == game_code))).scalar_one_or_none()
    if game is None:
        raise NotFoundError(f"Unknown game_code '{game_code}'")

    result = await db.execute(
        delete(RoundGames).where(RoundGames.round_id == round_id, RoundGames.game_id == game.game_id)
    )
    await db.commit()
    if result.rowcount == 0:
        raise NotFoundError("This game is not in the round's lineup")


# ---------------------------------------------------------------------------
# §2.9 Admin Account Management
# ---------------------------------------------------------------------------


async def create_admin(db: AsyncSession, *, username: str, password: str, role) -> Admin:
    admin = Admin(username=username, password_hash=hash_password(password), role=role)
    db.add(admin)
    await db.flush()
    await db.commit()
    await db.refresh(admin)
    return admin


async def list_admins(db: AsyncSession) -> list[Admin]:
    return (await db.execute(select(Admin).order_by(Admin.username))).scalars().all()


async def reset_admin_password(db: AsyncSession, *, admin_id: uuid.UUID, new_password: str) -> Admin:
    admin = await db.get(Admin, admin_id)
    if admin is None:
        raise NotFoundError("Admin not found")
    admin.password_hash = hash_password(new_password)
    await db.commit()
    await db.refresh(admin)
    return admin


async def assign_admin_room(db: AsyncSession, *, admin_id: uuid.UUID, room_id: uuid.UUID | None) -> Admin:
    """§2.9: bind (room_id given) or unbind (room_id=None) a ROOM_ADMIN's
    single-room boundary. See Admin.room_id and deps.assert_admin_room_access."""
    admin = await db.get(Admin, admin_id)
    if admin is None:
        raise NotFoundError("Admin not found")
    if room_id is not None:
        from app.models.round import Room

        room = await db.get(Room, room_id)
        if room is None:
            raise NotFoundError("Room not found")
    admin.room_id = room_id
    await db.commit()
    await db.refresh(admin)
    return admin


async def deactivate_admin(db: AsyncSession, *, admin_id: uuid.UUID, current_admin_id: uuid.UUID) -> None:
    if admin_id == current_admin_id:
        raise ConflictError("Cannot deactivate your own admin account")
    admin = await db.get(Admin, admin_id)
    if admin is None:
        raise NotFoundError("Admin not found")
    # The schema has no soft-delete/is_active column for admins, so this is
    # a hard delete. If audit-trail retention matters, add an `is_active`
    # column via a migration and flip it here instead.
    await db.delete(admin)
    await db.commit()
