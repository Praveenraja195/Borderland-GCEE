import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.core.exceptions import NotFoundError
from app.db.session import get_db
from app.models.admin import AdminRole
from app.schemas.admin import SchedulerJobCreate, SchedulerJobOut
from app.services import session_service
from app.workers.scheduler import schedule_round_close, scheduler

router = APIRouter(prefix="/admin/scheduler", tags=["admin-scheduler"])


def _job_to_out(job) -> SchedulerJobOut:
    # Job ids are minted as f"close_{game_code.lower()}_{round_id}" by
    # schedule_round_close(); round_id is also available as job.args[0].
    # game_code itself can contain underscores (e.g. "king_diamond"), but a
    # UUID never does, so everything between the "close" prefix and the
    # trailing UUID segment belongs to the game code — not just index 1,
    # which used to truncate "KING_DIAMOND" down to "KING". §2.11/§3 note:
    # this is still a string-split heuristic, fine while there are only 3
    # known game codes — see the module docstring if a 4th game is ever
    # added with an underscore-heavy or UUID-shaped code segment.
    game_code = None
    if job.id.startswith("close_"):
        parts = job.id.split("_")
        game_code = "_".join(parts[1:-1]).upper() if len(parts) > 2 else None
    round_id = str(job.args[0]) if job.args else None
    return SchedulerJobOut(job_id=job.id, game_code=game_code, round_id=round_id, run_date=job.next_run_time)


@router.get("/jobs", response_model=list[SchedulerJobOut])
async def list_scheduler_jobs(
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    """Audit Issue 3 visibility: lets an admin confirm scheduled round-close
    jobs actually survived a restart (now that they're in RedisJobStore
    instead of MemoryJobStore)."""
    return [_job_to_out(job) for job in scheduler.get_jobs()]


@router.get("/jobs/by-round/{round_id}/{game_code}", response_model=list[SchedulerJobOut])
async def list_jobs_for_round(
    round_id: uuid.UUID,
    game_code: str,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    """§1 item 3 — scheduler grouping. Lists exactly which close jobs a
    round-wide pause/stop (POST /admin/rounds/{round_id}/sessions/{game_code}
    /pause etc.) is about to cancel, *before* it does it, so an admin UI's
    'pause this game everywhere' button can show the blast radius first."""
    game_round_ids = await session_service.list_game_round_ids_for_round(
        db, round_id=round_id, game_code=game_code.upper()
    )
    wanted_ids = {f"close_{game_code.lower()}_{rid}" for rid in game_round_ids}
    return [_job_to_out(job) for job in scheduler.get_jobs() if job.id in wanted_ids]


@router.post("/jobs", response_model=SchedulerJobOut)
async def create_scheduler_job(
    payload: SchedulerJobCreate,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    """Re-registers a close job — for recovering a job that was
    accidentally deleted, or scheduling one that was never created.

    Audit §2.10: previously scheduled directly from admin-supplied
    round_id/run_at with no check that a game-round row with that id
    actually exists for that game_code. A typo'd round_id used to silently
    register a job that would fire at run_at, look up a nonexistent round,
    log a warning, and no-op. Now validates the round exists first so a typo
    surfaces immediately as a 404 instead of a job that quietly does
    nothing later."""
    round_model = session_service._ROUND_MODEL_BY_GAME_CODE.get(payload.game_code.upper())
    if round_model is None:
        raise NotFoundError(
            "game_code must be one of MINDMAZE, ACE_SPADE, KING_DIAMOND, JACK_HEART"
        )
    round_row = await db.get(round_model, payload.round_id)
    if round_row is None:
        raise NotFoundError(f"No {payload.game_code} round found with id {payload.round_id}")

    schedule_round_close(payload.game_code.upper(), payload.round_id, payload.run_at)
    job_id = f"close_{payload.game_code.lower()}_{payload.round_id}"
    job = scheduler.get_job(job_id)
    if job is None:
        raise NotFoundError("Job registration failed — check game_code is one of MINDMAZE, ACE_SPADE, KING_DIAMOND, JACK_HEART")
    return _job_to_out(job)


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_scheduler_job(
    job_id: str,
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    job = scheduler.get_job(job_id)
    if job is None:
        raise NotFoundError("Job not found")
    scheduler.remove_job(job_id)
