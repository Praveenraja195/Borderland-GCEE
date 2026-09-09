import pytest
from app.services.ace_spade_service import compute_round_score


def test_ace_spade_compute_round_score():
    # 8 correct, 0 wrong -> 16.0
    assert compute_round_score(8, 0) == 16.0

    # 1 correct, 2 wrong -> (1 * 2.0) - (2 * 0.5) = 1.0 (was 0.0 with the bug)
    assert compute_round_score(1, 2) == 1.0

    # 4 correct, 1 wrong -> (4 * 2.0) - (1 * 0.5) = 7.5
    assert compute_round_score(4, 1) == 7.5

    # 1 correct, 6 wrong -> (1 * 2.0) - (6 * 0.5) = -1.0 -> floored at 0.0
    assert compute_round_score(1, 6) == 0.0

    # 0 correct, 0 wrong -> 0.0
    assert compute_round_score(0, 0) == 0.0

    # 0 correct, 8 wrong -> 0.0
    assert compute_round_score(0, 8) == 0.0


@pytest.mark.asyncio
async def test_db_trigger_scoring():
    from app.db.session import async_session_maker
    from app.models.ace_spade import AceSpadeResult, AceSpadeRound
    from app.models.team import Team
    from sqlalchemy import select

    async with async_session_maker() as db:
        round_obj = (await db.execute(select(AceSpadeRound))).scalars().first()
        if not round_obj:
            pytest.skip("No AceSpadeRound in DB")
        team = (await db.execute(select(Team))).scalars().first()
        if not team:
            pytest.skip("No Team in DB")

        existing = (
            await db.execute(
                select(AceSpadeResult).where(
                    AceSpadeResult.round_id == round_obj.round_id,
                    AceSpadeResult.team_id == team.team_id,
                )
            )
        ).scalar_one_or_none()

        if existing is not None:
            # Check existing row
            expected = compute_round_score(existing.correct_picks, existing.wrong_picks)
            assert float(existing.round_score) == expected
        else:
            result = AceSpadeResult(
                round_id=round_obj.round_id,
                team_id=team.team_id,
                moves=8,
                wrong_picks=0,
                correct_picks=8,
            )
            try:
                db.add(result)
                await db.flush()
                assert float(result.round_score) == 16.0
            finally:
                await db.rollback()

