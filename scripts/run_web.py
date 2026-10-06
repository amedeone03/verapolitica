from __future__ import annotations

import os
import sys

from backend.app.core.config import Settings, get_settings
from backend.app.core.logging import configure_logging


def listen_port(settings: Settings) -> str:
    """Use Render's PORT when the platform sets it; otherwise the app setting."""

    if os.environ.get("RENDER") == "true":
        port = os.environ.get("PORT", "").strip()
        if port:
            return port
    return str(settings.web_port)


def gunicorn_argv(settings: Settings) -> list[str]:
    return [
        "gunicorn",
        "backend.app.main:app",
        "-k",
        "uvicorn.workers.UvicornWorker",
        "--bind",
        f"{settings.web_host}:{listen_port(settings)}",
        "--workers",
        str(settings.web_workers),
        "--timeout",
        "60",
        "--graceful-timeout",
        "30",
        "--access-logfile",
        "-",
        "--error-logfile",
        "-",
        "--capture-output",
    ]


def main() -> int:
    settings = get_settings()
    configure_logging(settings)
    sys.argv = gunicorn_argv(settings)
    from gunicorn.app.wsgiapp import run

    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
