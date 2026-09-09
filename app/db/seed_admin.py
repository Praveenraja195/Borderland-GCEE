import asyncio
import logging
import os

from sqlalchemy import select, func

from app.core.security import hash_password
from app.db.session import async_session_maker
from app.models.admin import Admin, AdminRole
from app.models.game import Game, RoundGames, GameSession, SessionStatus
from app.models.round import Round, Room, RoundStatus, RoomStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("round1.seed")

DEFAULT_ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")


async def seed_default_admin() -> None:
    async with async_session_maker() as db:
        # 1. Seed super admin
        result = await db.execute(
            select(Admin).where(Admin.username == DEFAULT_ADMIN_USERNAME)
        )
        existing = result.scalar_one_or_none()
        if not existing:
            hashed_pw = hash_password(DEFAULT_ADMIN_PASSWORD)
            new_admin = Admin(
                username=DEFAULT_ADMIN_USERNAME,
                password_hash=hashed_pw,
                role=AdminRole.SUPER_ADMIN,
            )
            db.add(new_admin)
            logger.info(
                "Created default SUPER_ADMIN user '%s' with password '%s'.",
                DEFAULT_ADMIN_USERNAME,
                DEFAULT_ADMIN_PASSWORD,
            )

        # 2. Check if any round exists; if not, create default Round 1
        round_result = await db.execute(select(Round).limit(1))
        existing_round = round_result.scalar_one_or_none()
        if not existing_round:
            round_obj = Round(
                round_number=1,
                name="Round 1",
                status=RoundStatus.ACTIVE,
            )
            db.add(round_obj)
            await db.flush()

            rooms = []
            for n in range(1, 11):
                room = Room(
                    round_id=round_obj.round_id,
                    room_number=n,
                    room_code=f"R{n:02d}",
                    status=RoomStatus.ACTIVE,
                )
                db.add(room)
                rooms.append(room)
            await db.flush()

            games_res = await db.execute(select(Game))
            games_list = games_res.scalars().all()
            game_map = {g.code: g for g in games_list}

            orders = [("MINDMAZE", 1), ("ACE_SPADE", 2), ("KING_DIAMOND", 3), ("JACK_HEART", 4)]
            for code, order in orders:
                if code in game_map:
                    rg = RoundGames(
                        round_id=round_obj.round_id,
                        game_id=game_map[code].game_id,
                        game_order=order,
                    )
                    db.add(rg)
            await db.flush()

            for room in rooms:
                for code, _ in orders:
                    if code in game_map:
                        gs = GameSession(
                            round_id=round_obj.round_id,
                            room_id=room.room_id,
                            game_id=game_map[code].game_id,
                            status=SessionStatus.NOT_STARTED,
                        )
                        db.add(gs)

            logger.info("Seeded default Round 1 with 10 rooms (R01-R10) and game sessions.")

        # 3. Ensure any ACTIVE round has rooms (1..10) seeded
        active_rounds = (
            await db.execute(select(Round).where(Round.status == RoundStatus.ACTIVE))
        ).scalars().all()
        for r in active_rounds:
            room_cnt = (
                await db.execute(
                    select(func.count()).select_from(Room).where(Room.round_id == r.round_id)
                )
            ).scalar_one()
            if room_cnt == 0:
                for n in range(1, 11):
                    db.add(
                        Room(
                            round_id=r.round_id,
                            room_number=n,
                            room_code=f"R{n:02d}",
                            status=RoomStatus.ACTIVE,
                        )
                    )
                logger.info("Seeded 10 missing rooms for ACTIVE round %s", r.round_id)

        await db.commit()


if __name__ == "__main__":
    asyncio.run(seed_default_admin())
