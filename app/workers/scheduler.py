"""
APScheduler setup, in-process, backed by a Redis job store so scheduled
closes survive an API process restart. Swap for Celery + celery-beat if you
outgrow a single process (see design doc §7).
"""

import logging
import uuid
from datetime import datetime
from urllib.parse import urlparse

from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings

logger = logging.getLogger("round1.scheduler")

# Audit Issue 3: MemoryJobStore keeps every scheduled close job only in RAM.
# A crash, OOM kill, or redeploy mid-event wipes all pending jobs, rounds
# never auto-close, game_scores never populates, and the leaderboard
# freezes. RedisJobStore persists jobs so they survive a process restart —
# a separate worker process (or the same API process after a redeploy)
# picks up right where it left off.
_parsed_redis = urlparse(settings.redis_url)
# Use a dedicated DB index (db=1) so scheduler job data never collides with
# the pub/sub traffic used for the live leaderboard (db=0).
_JOBSTORE_DB = 1

jobstores = {
    "default": RedisJobStore(
        host=_parsed_redis.hostname or "localhost",
        port=_parsed_redis.port or 6379,
        db=_JOBSTORE_DB,
        password=_parsed_redis.password,
    )
}
executors = {"default": AsyncIOExecutor()}

scheduler = AsyncIOScheduler(jobstores=jobstores, executors=executors, timezone="UTC")


def start_scheduler() -> None:
    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started")


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down")


def schedule_round_close(game_code: str, round_id: uuid.UUID, deadline: datetime) -> None:
    if deadline is None:
        return

    # Validate deadline is not in the past (allow 5s buffer for processing delay)
    from datetime import timezone as tz, timedelta
    now = datetime.now(tz.utc)
    if deadline < now - timedelta(seconds=5):
        logger.warning(f"Attempted to schedule {game_code} round {round_id} with past deadline {deadline}. Skipping.")
        return

    from app.workers import jobs

    job_map = {
        "MINDMAZE": jobs.close_mindmaze_round,
        "ACE_SPADE": jobs.close_ace_spade_round,
        "KING_DIAMOND": jobs.close_king_diamond_round,
        "JACK_HEART": jobs.close_jack_heart_round,
    }
    func = job_map.get(game_code)
    if func is None:
        logger.warning("No close-job registered for game_code=%s", game_code)
        return

    scheduler.add_job(
        func,
        trigger="date",
        run_date=deadline,
        args=[round_id],
        id=f"close_{game_code.lower()}_{round_id}",
        replace_existing=True,
        misfire_grace_time=60,  # Reduced from 300s (5 min) to 60s (1 min) to prevent stale score delays
    )


def cancel_round_close(game_code: str, round_id: uuid.UUID) -> None:
    """Removes a previously-scheduled close job, e.g. when an admin pauses a
    session so the round doesn't get auto-closed mid-pause, or restarts a
    session whose round rows are being deleted out from under the job.
    Safe to call even if the job was never registered or already fired."""
    job_id = f"close_{game_code.lower()}_{round_id}"
    if scheduler.get_job(job_id) is not None:
        scheduler.remove_job(job_id)


def validate_active_deadlines(rounds: list) -> None:
    """Warn if any active round (started but not closed) is missing a deadline.
    This catches setup errors where start_time was set but deadline wasn't."""
    now = datetime.now(datetime.now().astimezone().tzinfo or __import__('datetime').timezone.utc)
    for round_obj in rounds:
        is_active = (
            getattr(round_obj, 'start_time', None) is not None and
            not getattr(round_obj, 'is_closed', False)
        )
        if is_active and getattr(round_obj, 'deadline', None) is None:
            logger.warning(
                f"Active round {getattr(round_obj, 'round_id', '?')} "
                f"has start_time but no deadline. Rounds will never auto-close."
            )


if __name__ == "__main__":
    """Standalone entrypoint (`python -m app.workers.scheduler`): since jobs
    now live in RedisJobStore, this can run as a separate worker process
    that picks up jobs registered by the API process (or by itself), so
    scheduled closes keep firing even if the API process restarts."""
    import asyncio

    async def _run_forever():
        start_scheduler()
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            shutdown_scheduler()

    asyncio.run(_run_forever())
