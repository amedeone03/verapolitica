from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import func, inspect, select, text

from backend.app.core.config import AppEnvironment, Settings, get_settings
from backend.app.db.schema import current_revision, head_revision, is_postgresql
from backend.app.db.session import create_db_engine
from backend.app.jobs.catalog import enabled_schedules
from backend.app.models.civic import GlossaryTerm, Referendum, VotingGuide


REQUIRED_TABLES = (
    "politicians",
    "proposals",
    "referendums",
    "glossary_terms",
    "ingestion_job_runs",
    "regions",
    "municipalities",
)


def _safe_settings_dump(settings: Settings) -> dict[str, object]:
    return {
        "env": settings.env.value,
        "dialect": "postgresql" if is_postgresql(settings.database_url) else "other",
        "demo_ui_enabled": settings.demo_ui_enabled,
        "api_docs_enabled": settings.api_docs_enabled,
        "log_format": settings.resolved_log_format,
        "ai_extraction_enabled": settings.ai_extraction_enabled,
        "scheduler_enabled": settings.scheduler_enabled,
        "web_workers": settings.web_workers,
        "job_stale_after_minutes": settings.job_stale_after_minutes,
        "cors_origin_count": len(settings.cors_origin_list),
        "trusted_host_count": len(settings.trusted_host_list),
    }


def main() -> int:
    settings = get_settings()
    report: dict[str, object] = {
        "ok": True,
        "settings": _safe_settings_dump(settings),
        "checks": [],
    }
    failures: list[str] = []

    engine = create_db_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle,
    )
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        report["checks"].append("database_connect")
        tables = set(inspect(engine).get_table_names())
        missing = [name for name in REQUIRED_TABLES if name not in tables]
        if missing:
            failures.append(f"missing tables: {', '.join(missing)}")
        else:
            report["checks"].append("required_tables")
        revision = current_revision(engine)
        head = head_revision(settings.database_url)
        report["schema_revision"] = revision
        report["schema_head"] = head
        if is_postgresql(settings.database_url) and revision != head:
            failures.append("schema revision is not Alembic head")
        else:
            report["checks"].append("schema_revision")
        if "referendums" in tables:
            with engine.connect() as connection:
                synthetic = connection.execute(
                    select(func.count(Referendum.id)).where(Referendum.is_synthetic.is_(True))
                ).scalar() or 0
                guides = connection.execute(
                    select(func.count(VotingGuide.id)).where(VotingGuide.is_synthetic.is_(True))
                ).scalar() or 0
                terms = connection.execute(
                    select(func.count(GlossaryTerm.id)).where(GlossaryTerm.is_synthetic.is_(True))
                ).scalar() or 0
            report["synthetic_referendums"] = synthetic
            report["synthetic_voting_guides"] = guides
            report["synthetic_glossary_terms"] = terms
            if settings.env is AppEnvironment.PRODUCTION and (synthetic or guides or terms):
                failures.append("synthetic civic records present in production")
            else:
                report["checks"].append("synthetic_guard")
    except Exception as exc:
        failures.append(f"database check failed: {type(exc).__name__}")
    finally:
        engine.dispose()

    storage = Path(settings.raw_storage_path).expanduser()
    try:
        storage.mkdir(parents=True, exist_ok=True)
        probe = storage / ".verapolitica-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        report["checks"].append("raw_storage_writable")
    except OSError:
        failures.append("raw storage is not writable")

    invalid_schedules = []
    from apscheduler.triggers.cron import CronTrigger

    for spec, cron in enabled_schedules(settings):
        try:
            CronTrigger.from_crontab(cron, timezone="UTC")
        except (ValueError, TypeError):
            invalid_schedules.append(spec.job_name)
    if invalid_schedules:
        failures.append(f"invalid cron for jobs: {', '.join(invalid_schedules)}")
    else:
        report["checks"].append("scheduler_cron")

    blob = json.dumps(report)
    if "password" in blob.casefold() or "postgresql+psycopg://" in blob:
        failures.append("release report included a secret-like value")
    report["ok"] = not failures
    report["failures"] = failures
    print(json.dumps(report, indent=2, default=str))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
