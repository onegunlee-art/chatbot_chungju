"""매일 저녁 9시(한국시간) 수집 스케줄러."""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings
from app.ingest.pipeline import run_ingest

log = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
JOB_ID = "daily_ingest"


async def _job() -> None:
    try:
        await run_ingest(trigger="schedule")
    except Exception:
        # 스케줄러 스레드에서 예외가 새어나가면 다음 실행이 막힐 수 있다
        log.exception("정기 수집 작업이 실패했습니다.")


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    s = get_settings()
    _scheduler = AsyncIOScheduler(timezone=s.timezone)
    _scheduler.add_job(
        _job,
        CronTrigger(hour=s.ingest_cron_hour, minute=s.ingest_cron_minute, timezone=s.timezone),
        id=JOB_ID,
        max_instances=1,
        coalesce=True,          # 밀린 실행이 여러 번 쌓여도 한 번만
        misfire_grace_time=3600,
    )
    _scheduler.start()
    log.info(
        "일일 수집 예약됨: 매일 %02d:%02d (%s)",
        s.ingest_cron_hour, s.ingest_cron_minute, s.timezone,
    )
    return _scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def next_run_time() -> str | None:
    if _scheduler is None:
        return None
    job = _scheduler.get_job(JOB_ID)
    return job.next_run_time.isoformat() if job and job.next_run_time else None
