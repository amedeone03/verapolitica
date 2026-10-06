from __future__ import annotations

import logging
import sys
import time

from backend.app.core.config import get_settings
from backend.app.db.schema import require_persistent_schema
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.jobs import IngestionScheduler, enabled_schedules


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("verapolitica.scheduler")


def main() -> int:
    settings = get_settings()
    engine = create_db_engine(settings.database_url)
    scheduler: IngestionScheduler | None = None
    try:
        require_persistent_schema(engine, settings)
        configured = tuple(
            spec.job_name for spec, _cron in enabled_schedules(settings)
        )
        if not configured:
            logger.info(
                "no ingestion schedules enabled; set VERAPOLITICA_SCHEDULE_*_CRON"
            )
        scheduler = IngestionScheduler(
            settings, create_session_factory(engine)
        )
        registered = scheduler.start()
        logger.info("scheduler registered jobs: %s", ",".join(registered) or "(none)")
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        logger.info("scheduler stopping")
        return 0
    except Exception:
        logger.exception("scheduler failed to start")
        return 1
    finally:
        if scheduler is not None:
            scheduler.shutdown()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
