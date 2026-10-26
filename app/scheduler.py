"""Background scheduling of collection syncs (APScheduler, thread pool)."""
import logging
from datetime import datetime

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import db, sync

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def validate_cron(expr: str) -> None:
    """Raises ValueError for an invalid 5-field cron expression."""
    CronTrigger.from_crontab(expr)


def start() -> None:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(executors={"default": ThreadPoolExecutor(4)},
                                         job_defaults={"coalesce": True, "max_instances": 1,
                                                       "misfire_grace_time": 3600})
        _scheduler.start()
        # Home screen calendars switch on/off just after midnight, and once at startup.
        _scheduler.add_job(sync.apply_home_calendars, CronTrigger(hour=0, minute=1),
                           id="home-calendars", name="Home screen calendars",
                           replace_existing=True)
        _scheduler.add_job(sync.apply_home_calendars, id="home-calendars-startup",
                           name="Home screen calendars (startup)", replace_existing=True)
    reload_jobs()


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def reload_jobs() -> None:
    """(Re)create one cron job per enabled collection."""
    if _scheduler is None:
        return
    default = db.get_settings().get("default_schedule") or ""
    wanted = set()
    for row in db.list_collections():
        cfg = row["config"]
        expr = cfg.get("schedule") or default
        if not cfg.get("enabled", True) or not expr:
            continue
        job_id = f"collection-{row['id']}"
        try:
            trigger = CronTrigger.from_crontab(expr)
        except ValueError:
            log.warning("Invalid schedule '%s' for collection '%s'", expr, cfg.get("name"))
            continue
        _scheduler.add_job(sync.run_collection, trigger, args=[row["id"], "schedule"],
                           id=job_id, name=cfg.get("name"), replace_existing=True)
        wanted.add(job_id)
    for job in _scheduler.get_jobs():
        if job.id.startswith("collection-") and job.id not in wanted:
            job.remove()


def next_run(collection_id: int) -> str | None:
    if _scheduler is None:
        return None
    job = _scheduler.get_job(f"collection-{collection_id}")
    if job and job.next_run_time:
        return job.next_run_time.isoformat(timespec="seconds")
    return None


def run_now(collection_id: int, trigger: str = "manual") -> None:
    """Queue an immediate sync in the background."""
    if _scheduler is None:
        sync.run_collection(collection_id, trigger)
        return
    _scheduler.add_job(sync.run_collection, args=[collection_id, trigger],
                       id=f"now-{collection_id}-{datetime.now().timestamp()}",
                       name=f"Run {collection_id}")
