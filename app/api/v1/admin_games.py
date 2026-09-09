import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import assert_admin_room_access, require_role
from app.core.exceptions import ConflictError, NotFoundError
from app.db.session import get_db
from app.models.ace_spade import AceSpadeResult, AceSpadeRound
from app.models.admin import Admin, AdminRole
from app.models.game import GameSession, SessionStatus
from app.models.jack_heart import JackHeartAnswer, JackHeartAssignment, JackHeartRound, JHSymbol
from app.models.king_diamond import KingDiamondRound, KingDiamondSubmission
from app.models.mindmaze import MindmazeResult, MindmazeRound
from app.models.team import Team
from app.schemas.ace_spade import AceSpadeResultOut, AceSpadeResultOverride
from app.schemas.jack_heart import JackHeartAnswerOut, JackHeartAssignmentAdminOut
from app.schemas.king_diamond import KingDiamondSubmissionOut, KingDiamondSubmissionOverride
from app.schemas.mindmaze import MindmazeResultOut, MindmazeResultOverride
from app.workers import jobs

router = APIRouter(prefix="/admin", tags=["admin-games"])


# ---------------------------------------------------------------------------
# MindMaze
# ---------------------------------------------------------------------------


@router.post("/mindmaze/rounds/{round_id}/force-close", status_code=status.HTTP_204_NO_CONTENT)
async def force_close_mindmaze_round(
    round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    round_obj = await db.get(MindmazeRound, round_id)
    if round_obj is None:
        raise NotFoundError("MindMaze round not found")
    session = await db.get(GameSession, round_obj.session_id)
    if session is not None:
        assert_admin_room_access(admin, session.room_id)  # §2.9
        if session.status == SessionStatus.PAUSED:
            raise ConflictError("Resume the session before force-closing one of its rounds.")
    await jobs.close_mindmaze_round(round_id)


@router.get("/mindmaze/rounds/{round_id}/results", response_model=list[MindmazeResultOut])
async def list_mindmaze_results(
    round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    round_obj = await db.get(MindmazeRound, round_id)
    if round_obj is None:
        raise NotFoundError("MindMaze round not found")
    return (
        (await db.execute(select(MindmazeResult).where(MindmazeResult.round_id == round_id))).scalars().all()
    )


@router.patch("/mindmaze/rounds/{round_id}/results/{team_id}", response_model=MindmazeResultOut)
async def override_mindmaze_result(
    round_id: uuid.UUID,
    team_id: uuid.UUID,
    payload: MindmazeResultOverride,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    """Adjudication escape hatch — overrides the score computed by
    trg_mm_score (Audit Issue 1). The trigger only fires on INSERT, so this
    UPDATE is safe from being immediately recomputed away."""
    result = (
        await db.execute(
            select(MindmazeResult).where(MindmazeResult.round_id == round_id, MindmazeResult.team_id == team_id)
        )
    ).scalar_one_or_none()
    if result is None:
        raise NotFoundError("No MindMaze result found for this team in this round")

    result.round_score = payload.round_score
    await db.commit()
    await db.refresh(result)
    return result


# ---------------------------------------------------------------------------
# Ace of Spades
# ---------------------------------------------------------------------------


@router.post("/ace-spade/rounds/{round_id}/force-close", status_code=status.HTTP_204_NO_CONTENT)
async def force_close_ace_spade_round(
    round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    round_obj = await db.get(AceSpadeRound, round_id)
    if round_obj is None:
        raise NotFoundError("Ace of Spades round not found")
    session = await db.get(GameSession, round_obj.session_id)
    if session is not None:
        assert_admin_room_access(admin, session.room_id)
        if session.status == SessionStatus.PAUSED:
            raise ConflictError("Resume the session before force-closing one of its rounds.")
    await jobs.close_ace_spade_round(round_id)


@router.get("/ace-spade/rounds/{round_id}/results", response_model=list[AceSpadeResultOut])
async def list_ace_spade_results(
    round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    round_obj = await db.get(AceSpadeRound, round_id)
    if round_obj is None:
        raise NotFoundError("Ace of Spades round not found")
    return (
        (await db.execute(select(AceSpadeResult).where(AceSpadeResult.round_id == round_id))).scalars().all()
    )


@router.patch("/ace-spade/rounds/{round_id}/results/{team_id}", response_model=AceSpadeResultOut)
async def override_ace_spade_result(
    round_id: uuid.UUID,
    team_id: uuid.UUID,
    payload: AceSpadeResultOverride,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    """Adjudication escape hatch — overrides the score computed by
    trg_as_score. The trigger only fires on INSERT, so this
    UPDATE is safe from being immediately recomputed away."""
    result = (
        await db.execute(
            select(AceSpadeResult).where(AceSpadeResult.round_id == round_id, AceSpadeResult.team_id == team_id)
        )
    ).scalar_one_or_none()
    if result is None:
        raise NotFoundError("No Ace of Spades result found for this team in this round")

    result.round_score = payload.round_score
    await db.commit()
    await db.refresh(result)
    return result


# ---------------------------------------------------------------------------
# King of Diamonds
# ---------------------------------------------------------------------------


@router.post("/king-diamond/rounds/{round_id}/force-close", status_code=status.HTTP_204_NO_CONTENT)
async def force_close_king_diamond_round(
    round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    round_obj = await db.get(KingDiamondRound, round_id)
    if round_obj is None:
        raise NotFoundError("King of Diamonds round not found")
    session = await db.get(GameSession, round_obj.session_id)
    if session is not None:
        assert_admin_room_access(admin, session.room_id)  # §2.9
        # §3: force-closing a round while its session is PAUSED bypasses
        # the PAUSED guard that _maybe_close_session enforces at the
        # session level — the round itself would still get closed/scored
        # even though teams shouldn't be able to submit during a pause.
        if session.status == SessionStatus.PAUSED:
            raise ConflictError("Resume the session before force-closing one of its rounds.")
    await jobs.close_king_diamond_round(round_id)


@router.get("/king-diamond/rounds/{round_id}/submissions", response_model=list[KingDiamondSubmissionOut])
async def list_king_diamond_submissions(
    round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    round_obj = await db.get(KingDiamondRound, round_id)
    if round_obj is None:
        raise NotFoundError("King of Diamonds round not found")
    return (
        (
            await db.execute(
                select(KingDiamondSubmission).where(KingDiamondSubmission.round_id == round_id)
            )
        )
        .scalars()
        .all()
    )


@router.patch(
    "/king-diamond/rounds/{round_id}/submissions/{submission_id}", response_model=KingDiamondSubmissionOut
)
async def override_king_diamond_submission(
    round_id: uuid.UUID,
    submission_id: uuid.UUID,
    payload: KingDiamondSubmissionOverride,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    """Adjudication escape hatch, e.g. to disqualify a submission."""
    submission = await db.get(KingDiamondSubmission, submission_id)
    if submission is None or submission.round_id != round_id:
        raise NotFoundError("Submission not found for this round")

    if payload.is_valid is not None:
        submission.is_valid = payload.is_valid
    if payload.round_score is not None:
        submission.round_score = payload.round_score
    await db.commit()
    await db.refresh(submission)
    return submission


# ---------------------------------------------------------------------------
# Jack of Hearts
# ---------------------------------------------------------------------------


@router.post("/jack-heart/rounds/{round_id}/force-close", status_code=status.HTTP_204_NO_CONTENT)
async def force_close_jack_heart_round(
    round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    round_obj = await db.get(JackHeartRound, round_id)
    if round_obj is None:
        raise NotFoundError("Jack of Hearts round not found")
    session = await db.get(GameSession, round_obj.session_id)
    if session is not None:
        assert_admin_room_access(admin, session.room_id)  # §2.9
        if session.status == SessionStatus.PAUSED:
            raise ConflictError("Resume the session before force-closing one of its rounds.")
    await jobs.close_jack_heart_round(round_id)


@router.get("/jack-heart/rounds/{round_id}/answers", response_model=list[JackHeartAnswerOut])
async def list_jack_heart_answers(
    round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    round_obj = await db.get(JackHeartRound, round_id)
    if round_obj is None:
        raise NotFoundError("Jack of Hearts round not found")
    return (
        (await db.execute(select(JackHeartAnswer).where(JackHeartAnswer.round_id == round_id))).scalars().all()
    )


@router.get(
    "/jack-heart/rounds/{round_id}/assignments", response_model=list[JackHeartAssignmentAdminOut]
)
async def list_jack_heart_assignments(
    round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    # Privileged: only SUPER_ADMIN, to prevent symbol leakage via a
    # compromised ROOM_ADMIN account (every team's hidden symbol is visible
    # here in one shot).
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    round_obj = await db.get(JackHeartRound, round_id)
    if round_obj is None:
        raise NotFoundError("Jack of Hearts round not found")

    rows = (
        await db.execute(
            select(
                Team.team_id,
                Team.team_code,
                Team.team_name,
                JHSymbol.symbol_id,
                JHSymbol.code,
                JHSymbol.label,
                JHSymbol.suit,
                JHSymbol.rank,
            )
            .join(JackHeartAssignment, JackHeartAssignment.team_id == Team.team_id)
            .join(JHSymbol, JHSymbol.symbol_id == JackHeartAssignment.symbol_id)
            .where(JackHeartAssignment.round_id == round_id)
        )
    ).all()
    return [
        JackHeartAssignmentAdminOut(
            team_id=row.team_id,
            team_code=row.team_code,
            team_name=row.team_name,
            symbol_id=row.symbol_id,
            symbol_code=row.code,
            symbol_label=row.label,
            suit=row.suit,
            rank=row.rank,
        )
        for row in rows
    ]
