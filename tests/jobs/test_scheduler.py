from apscheduler.schedulers.background import BackgroundScheduler

from backend.app.core.config import Settings
from backend.app.jobs.catalog import enabled_schedules
from backend.app.jobs.scheduler import IngestionScheduler


def test_enabled_schedules_skip_blank_cron():
    settings = Settings(
        schedule_senato_cron="0 3 * * *",
        schedule_camera_cron="  ",
        schedule_governo_cron="",
    )
    enabled = enabled_schedules(settings)
    assert tuple(spec.job_name for spec, _cron in enabled) == ("senato",)
    assert enabled[0][1] == "0 3 * * *"


def test_scheduler_registers_only_configured_jobs(session_factory):
    settings = Settings(
        schedule_senato_cron="15 4 * * *",
        schedule_proposals_cron="0 5 * * 1",
        schedule_camera_cron="",
    )
    scheduler = IngestionScheduler(
        settings,
        session_factory,
        scheduler=BackgroundScheduler(timezone="UTC"),
    )
    registered = scheduler.register()
    assert registered == ("senato", "proposals")
    assert scheduler.registered_job_names() == ("senato", "proposals")
    scheduler.shutdown()


def test_disabled_schedule_is_not_registered(session_factory):
    scheduler = IngestionScheduler(
        Settings(),
        session_factory,
        scheduler=BackgroundScheduler(timezone="UTC"),
    )
    assert scheduler.register() == ()
    assert scheduler.registered_job_names() == ()
    scheduler.shutdown()


def test_civic_reminders_schedule_registers(session_factory):
    scheduler = IngestionScheduler(
        Settings(schedule_civic_reminders_cron="0 6 * * *"),
        session_factory,
        scheduler=BackgroundScheduler(timezone="UTC"),
    )
    assert scheduler.register() == ("civic-reminders",)
    scheduler.shutdown()


def test_invalid_cron_is_skipped(session_factory):
    scheduler = IngestionScheduler(
        Settings(schedule_senato_cron="not-a-cron"),
        session_factory,
        scheduler=BackgroundScheduler(timezone="UTC"),
    )
    assert scheduler.register() == ()
    scheduler.shutdown()
