from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.app.core.config import get_settings
from scripts.backup_ops import (
    BackupError,
    archive_directory,
    archive_portraits,
    build_manifest,
    connection_identity,
    dump_postgres,
    file_record,
    manifest_name,
    portraits_archive_name,
    postgres_dump_name,
    prepare_output_dir,
    raw_archive_name,
    read_alembic_revision,
    refuse_demo_path,
    require_postgresql_url,
    utc_stamp,
    write_manifest,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a timestamped PostgreSQL custom-format dump, optional "
            "raw-storage archive, and a secret-free manifest."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("backups"),
        help="Directory for dump/archive/manifest files (default: backups/)",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override VERAPOLITICA_DATABASE_URL (do not pass a password on the CLI if avoidable)",
    )
    parser.add_argument(
        "--raw-storage-path",
        type=Path,
        default=None,
        help="Override VERAPOLITICA_RAW_STORAGE_PATH",
    )
    parser.add_argument(
        "--skip-raw",
        action="store_true",
        help="Dump PostgreSQL only (not recommended for disaster recovery)",
    )
    parser.add_argument(
        "--skip-postgres",
        action="store_true",
        help="Archive raw storage only",
    )
    parser.add_argument(
        "--include-portraits",
        action="store_true",
        help="Also archive VERAPOLITICA_PORTRAITS_PATH if configured",
    )
    return parser.parse_args(argv)


def run_backup(args: argparse.Namespace) -> dict[str, object]:
    settings = get_settings()
    database_url = args.database_url or settings.database_url
    raw_path = (args.raw_storage_path or settings.raw_storage_path).expanduser()
    if args.skip_postgres and args.skip_raw and not args.include_portraits:
        raise BackupError("nothing to back up; omit --skip-postgres/--skip-raw")
    if not args.skip_postgres:
        require_postgresql_url(database_url)

    output_dir = prepare_output_dir(args.output_dir)
    stamp = utc_stamp()
    identity = connection_identity(database_url) if not args.skip_postgres else {}
    alembic_revision = None if args.skip_postgres else read_alembic_revision(database_url)

    postgres_section: dict[str, object] | None = None
    raw_section: dict[str, object] | None = None
    portraits_section: dict[str, object] | None = None

    if not args.skip_postgres:
        dump_path = output_dir / postgres_dump_name(stamp)
        dump_postgres(database_url, dump_path)
        postgres_section = {
            **file_record(dump_path),
            "database": identity["database"],
            "host": identity["host"],
            "port": identity["port"],
            "format": "custom",
        }

    if not args.skip_raw:
        refuse_demo_path(raw_path, label="RAW_STORAGE_PATH")
        archive_path = output_dir / raw_archive_name(stamp)
        file_count = archive_directory(raw_path, archive_path, label="RAW_STORAGE_PATH")
        raw_section = {
            **file_record(archive_path),
            "file_count": file_count,
        }

    if args.include_portraits:
        if settings.portraits_path is None:
            raise BackupError("--include-portraits requires VERAPOLITICA_PORTRAITS_PATH")
        portraits_path = output_dir / portraits_archive_name(stamp)
        file_count = archive_portraits(settings.portraits_path, portraits_path)
        portraits_section = {
            **file_record(portraits_path),
            "file_count": file_count,
        }

    payload = build_manifest(
        stamp=stamp,
        environment=settings.env.value,
        alembic_revision=alembic_revision,
        postgres=postgres_section,
        raw_storage=raw_section,
        portraits=portraits_section,
    )
    manifest_path = output_dir / manifest_name(stamp)
    write_manifest(manifest_path, payload)
    payload["manifest_filename"] = manifest_path.name
    payload["output_dir"] = str(output_dir)
    return payload


def main(argv: list[str] | None = None) -> int:
    try:
        report = run_backup(parse_args(argv))
    except BackupError as exc:
        print(f"backup failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
