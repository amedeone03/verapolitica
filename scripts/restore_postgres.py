from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.db.schema import head_revision
from scripts.backup_ops import (
    BackupError,
    extract_archive,
    read_alembic_revision,
    restore_postgres,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Restore a VeraPolitica PostgreSQL custom-format dump and optional "
            "raw-storage archive. The target database must already exist. "
            "This command never drops the database."
        )
    )
    parser.add_argument(
        "--dump",
        type=Path,
        default=None,
        help="pg_dump custom-format (.dump) file produced by scripts.backup_postgres",
    )
    parser.add_argument(
        "--raw-archive",
        type=Path,
        default=None,
        help="Optional raw-storage .tar.gz archive",
    )
    parser.add_argument(
        "--portraits-archive",
        type=Path,
        default=None,
        help="Optional portraits .tar.gz archive",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Target PostgreSQL URL (default: VERAPOLITICA_DATABASE_URL)",
    )
    parser.add_argument(
        "--raw-storage-path",
        type=Path,
        default=None,
        help="Directory to extract raw storage into (default: VERAPOLITICA_RAW_STORAGE_PATH)",
    )
    parser.add_argument(
        "--portraits-dest",
        type=Path,
        default=None,
        help="Directory to extract portraits into",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm this destructive restore",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Alias for --yes",
    )
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help=(
            "Allow restore into a non-empty database or directory "
            "(pg_restore --clean --if-exists). Still requires --yes."
        ),
    )
    return parser.parse_args(argv)


def run_restore(args: argparse.Namespace) -> dict[str, object]:
    confirmed = bool(args.yes or args.force)
    if args.replace_existing and not confirmed:
        raise BackupError("--replace-existing requires --yes")
    if args.dump is None and args.raw_archive is None and args.portraits_archive is None:
        raise BackupError("pass --dump and/or --raw-archive (and optional --portraits-archive)")

    settings = get_settings()
    report: dict[str, object] = {
        "ok": True,
        "replaced_existing": bool(args.replace_existing),
    }

    if args.dump is not None:
        database_url = args.database_url or settings.database_url
        restore_postgres(
            database_url,
            args.dump,
            confirmed=confirmed,
            replace_existing=args.replace_existing,
        )
        revision = read_alembic_revision(database_url)
        report["alembic_revision"] = revision
        report["alembic_head"] = head_revision()
        report["postgres_dump"] = args.dump.name

    if args.raw_archive is not None:
        raw_dest = args.raw_storage_path or settings.raw_storage_path
        extract_archive(
            args.raw_archive,
            raw_dest,
            confirmed=confirmed,
            replace_existing=args.replace_existing,
            label="raw storage",
        )
        report["raw_archive"] = args.raw_archive.name
        report["raw_storage_path"] = str(raw_dest)

    if args.portraits_archive is not None:
        dest = args.portraits_dest
        if dest is None:
            if settings.portraits_path is None:
                raise BackupError("--portraits-archive requires --portraits-dest or VERAPOLITICA_PORTRAITS_PATH")
            dest = settings.portraits_path.parent
        extract_archive(
            args.portraits_archive,
            dest,
            confirmed=confirmed,
            replace_existing=args.replace_existing,
            label="portraits",
        )
        report["portraits_archive"] = args.portraits_archive.name

    return report


def main(argv: list[str] | None = None) -> int:
    try:
        report = run_restore(parse_args(argv))
    except BackupError as exc:
        print(f"restore failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
