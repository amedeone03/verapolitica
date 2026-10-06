from __future__ import annotations

import subprocess
import sys

from sqlalchemy.engine import make_url

from backend.app.core.config import get_settings


def main() -> int:
    """Apply Alembic head, then start the web process. Prints no credentials."""

    url = make_url(get_settings().database_url)
    print(
        "migrate_target",
        url.drivername,
        url.database,
        url.username,
        "password_set" if url.password else "password_missing",
        flush=True,
    )
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=False,
    )
    if completed.returncode != 0:
        return completed.returncode
    from scripts.run_web import main as serve

    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
