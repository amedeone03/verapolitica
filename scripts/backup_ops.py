from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from sqlalchemy import text
from sqlalchemy.engine import make_url

from backend.app.core.logging import sanitize_log_text
from backend.app.db.schema import current_revision, head_revision, is_postgresql, is_sqlite
from backend.app.db.session import create_db_engine


class BackupError(RuntimeError):
    """Operator-facing backup or restore failure."""


_DEMO_MARKERS = ("/ceo_demo/", "/unified_demo/", "/data/demo/")
_CUSTOM_DUMP_MAGIC = b"PGDMP"
_PG_BIN_CANDIDATES = (
    "/opt/homebrew/opt/postgresql@16/bin",
    "/opt/homebrew/opt/postgresql@17/bin",
    "/usr/lib/postgresql/16/bin",
    "/usr/pgsql-16/bin",
)


def utc_stamp(now: datetime | None = None) -> str:
    moment = now or datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def postgres_dump_name(stamp: str) -> str:
    _require_safe_stamp(stamp)
    return f"verapolitica-postgres-{stamp}.dump"


def raw_archive_name(stamp: str) -> str:
    _require_safe_stamp(stamp)
    return f"verapolitica-raw-{stamp}.tar.gz"


def portraits_archive_name(stamp: str) -> str:
    _require_safe_stamp(stamp)
    return f"verapolitica-portraits-{stamp}.tar.gz"


def manifest_name(stamp: str) -> str:
    _require_safe_stamp(stamp)
    return f"verapolitica-backup-{stamp}.json"


def _require_safe_stamp(stamp: str) -> None:
    if not stamp or any(item in stamp for item in ("/", "\\", "..")):
        raise BackupError("backup timestamp is invalid")


def find_pg_binary(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for directory in _PG_BIN_CANDIDATES:
        found = shutil.which(name, path=directory)
        if found:
            return found
    return None


def require_postgresql_url(database_url: str) -> None:
    if is_sqlite(database_url):
        raise BackupError("SQLite is not a supported production backup target")
    if not is_postgresql(database_url):
        raise BackupError("production backup requires a PostgreSQL DATABASE_URL")


def refuse_demo_path(path: Path, *, label: str) -> None:
    normalized = f"/{path.expanduser().resolve().as_posix().casefold().strip('/')}/"
    if any(marker in normalized for marker in _DEMO_MARKERS):
        raise BackupError(f"{label} must not use a demo/local data path")


def prepare_output_dir(path: Path) -> Path:
    output = path.expanduser()
    if output.exists() and not output.is_dir():
        raise BackupError(f"backup output path is not a directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    os.chmod(output, stat.S_IRWXU)
    return output.resolve()


def refuse_overwrite(path: Path) -> None:
    if path.exists():
        raise BackupError(f"refusing to overwrite existing backup file: {path}")


def refuse_output_inside_source(output: Path, source: Path) -> None:
    try:
        output.resolve().relative_to(source.expanduser().resolve())
    except ValueError:
        return
    raise BackupError("backup output directory must not be inside the source being archived")


def restrict_file(path: Path) -> None:
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, object]:
    return {
        "filename": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def connection_identity(database_url: str) -> dict[str, str]:
    require_postgresql_url(database_url)
    url = make_url(database_url)
    if not url.database:
        raise BackupError("DATABASE_URL is missing a database name")
    return {
        "host": url.host or "localhost",
        "port": str(url.port or 5432),
        "user": url.username or "",
        "database": url.database,
    }


def libpq_env(database_url: str, base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    require_postgresql_url(database_url)
    url = make_url(database_url)
    env = dict(base_env if base_env is not None else os.environ)
    if url.password is not None:
        env["PGPASSWORD"] = url.password
    env.pop("PGDATABASE", None)
    return env


def pg_dump_argv(database_url: str, destination: Path) -> list[str]:
    identity = connection_identity(database_url)
    binary = find_pg_binary("pg_dump")
    if not binary:
        raise BackupError("pg_dump was not found on PATH")
    argv = [binary, "--no-password", "-Fc", "-f", str(destination)]
    if identity["host"]:
        argv.extend(["-h", identity["host"]])
    argv.extend(["-p", identity["port"]])
    if identity["user"]:
        argv.extend(["-U", identity["user"]])
    argv.extend(["-d", identity["database"]])
    return argv


def pg_restore_argv(
    database_url: str,
    dump_file: Path,
    *,
    replace_existing: bool = False,
) -> list[str]:
    identity = connection_identity(database_url)
    binary = find_pg_binary("pg_restore")
    if not binary:
        raise BackupError("pg_restore was not found on PATH")
    argv = [binary, "--no-password", "--no-owner", "--no-acl"]
    if replace_existing:
        argv.extend(["--clean", "--if-exists"])
    if identity["host"]:
        argv.extend(["-h", identity["host"]])
    argv.extend(["-p", identity["port"]])
    if identity["user"]:
        argv.extend(["-U", identity["user"]])
    argv.extend(["-d", identity["database"], str(dump_file)])
    return argv


def argv_contains_secret(argv: list[str], database_url: str) -> bool:
    url = make_url(database_url)
    secret = url.password or ""
    if not secret:
        return False
    return secret in " ".join(argv)


def run_tool(argv: list[str], env: Mapping[str, str], *, label: str) -> None:
    completed = subprocess.run(
        argv,
        env=dict(env),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = sanitize_log_text(
            (completed.stderr or completed.stdout or "").strip()
        )
        raise BackupError(
            f"{label} failed with exit {completed.returncode}: {detail[:2000]}"
        )


def require_custom_dump(path: Path) -> None:
    if path.name.endswith(".sql") or path.suffix.casefold() == ".db":
        raise BackupError("restore requires a pg_dump custom-format (.dump) file")
    if not path.is_file() or path.stat().st_size == 0:
        raise BackupError(f"postgres dump is missing or empty: {path}")
    with path.open("rb") as handle:
        magic = handle.read(5)
    if magic != _CUSTOM_DUMP_MAGIC:
        raise BackupError("postgres dump is not a pg_dump custom-format (-Fc) file")


def public_table_count(database_url: str) -> int:
    require_postgresql_url(database_url)
    engine = create_db_engine(database_url, pool_size=1, max_overflow=0)
    try:
        with engine.connect() as connection:
            count = connection.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                )
            ).scalar_one()
        return int(count or 0)
    finally:
        engine.dispose()


def require_empty_database(database_url: str) -> None:
    count = public_table_count(database_url)
    if count:
        raise BackupError(
            "target PostgreSQL database is not empty; recreate it or pass "
            "--replace-existing with --yes"
        )


def require_confirmation(*, confirmed: bool, action: str) -> None:
    if not confirmed:
        raise BackupError(f"{action} is destructive; pass --yes (or --force) to confirm")


def read_alembic_revision(database_url: str) -> str | None:
    require_postgresql_url(database_url)
    engine = create_db_engine(database_url, pool_size=1, max_overflow=0)
    try:
        return current_revision(engine)
    finally:
        engine.dispose()


def dump_postgres(database_url: str, destination: Path) -> None:
    require_postgresql_url(database_url)
    refuse_overwrite(destination)
    argv = pg_dump_argv(database_url, destination)
    if argv_contains_secret(argv, database_url):
        raise BackupError("pg_dump command would expose a password")
    try:
        run_tool(argv, libpq_env(database_url), label="pg_dump")
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    if not destination.is_file() or destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
        raise BackupError("pg_dump produced an empty dump")
    require_custom_dump(destination)
    restrict_file(destination)


def restore_postgres(
    database_url: str,
    dump_file: Path,
    *,
    confirmed: bool,
    replace_existing: bool = False,
) -> None:
    require_postgresql_url(database_url)
    require_confirmation(confirmed=confirmed, action="postgres restore")
    if replace_existing and not confirmed:
        raise BackupError("--replace-existing requires --yes")
    require_custom_dump(dump_file)
    if not replace_existing:
        require_empty_database(database_url)
    argv = pg_restore_argv(
        database_url, dump_file, replace_existing=replace_existing
    )
    if argv_contains_secret(argv, database_url):
        raise BackupError("pg_restore command would expose a password")
    run_tool(argv, libpq_env(database_url), label="pg_restore")


def count_files(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(1 for path in root.rglob("*") if path.is_file())


def _exclude_secret_member(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    name = Path(info.name).name.casefold()
    if name.startswith(".env") or name.endswith(".dump") or name in {".ds_store"}:
        return None
    return info


def archive_directory(source: Path, destination: Path, *, label: str) -> int:
    root = source.expanduser().resolve()
    if not root.is_dir():
        raise BackupError(f"{label} path is not a directory: {root}")
    refuse_demo_path(root, label=label)
    refuse_output_inside_source(destination.parent, root)
    refuse_overwrite(destination)
    file_count = 0

    def _filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        nonlocal file_count
        kept = _exclude_secret_member(info)
        if kept is None:
            return None
        if info.isfile():
            file_count += 1
        return info

    with tarfile.open(destination, "w:gz") as archive:
        archive.add(root, arcname=".", filter=_filter)
    restrict_file(destination)
    return file_count


def archive_portraits(json_path: Path, destination: Path) -> int:
    portraits_json = json_path.expanduser().resolve()
    if not portraits_json.is_file():
        raise BackupError(f"portraits JSON is missing: {portraits_json}")
    refuse_demo_path(portraits_json.parent, label="portraits")
    refuse_overwrite(destination)
    images = portraits_json.parent / "portraits"
    file_count = 0

    def _filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        nonlocal file_count
        kept = _exclude_secret_member(info)
        if kept is None:
            return None
        if info.isfile():
            file_count += 1
        return info

    with tarfile.open(destination, "w:gz") as archive:
        archive.add(portraits_json, arcname=portraits_json.name, filter=_filter)
        if images.is_dir():
            archive.add(images, arcname="portraits", filter=_filter)
    restrict_file(destination)
    return file_count


def extract_archive(
    archive_path: Path,
    destination: Path,
    *,
    confirmed: bool,
    replace_existing: bool,
    label: str,
) -> None:
    require_confirmation(confirmed=confirmed, action=f"{label} restore")
    if not archive_path.is_file() or archive_path.stat().st_size == 0:
        raise BackupError(f"{label} archive is missing or empty: {archive_path}")
    suffix = "".join(archive_path.suffixes).casefold()
    if suffix not in {".tar.gz", ".tgz"}:
        raise BackupError(f"{label} archive must be a .tar.gz file")
    target = destination.expanduser().resolve()
    refuse_demo_path(target, label=f"{label} restore destination")
    if target.exists() and any(target.iterdir()) and not replace_existing:
        raise BackupError(
            f"{label} restore destination is not empty: {target}; "
            "pass --replace-existing with --yes"
        )
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as archive:
        archive.extractall(target, filter="data")


def manifest_is_safe(payload: Mapping[str, object]) -> bool:
    blob = json.dumps(payload, default=str).casefold()
    forbidden = (
        "password",
        "admin_api_key",
        "llm_api_key",
        "postgresql+psycopg://",
        "postgres://",
        "pgpassword",
        "secret_key",
    )
    return not any(token in blob for token in forbidden)


def build_manifest(
    *,
    stamp: str,
    environment: str,
    alembic_revision: str | None,
    postgres: dict[str, object] | None,
    raw_storage: dict[str, object] | None,
    portraits: dict[str, object] | None = None,
) -> dict[str, object]:
    identity = postgres or {}
    payload = {
        "app": "verapolitica",
        "created_at": stamp,
        "environment": environment,
        "alembic_revision": alembic_revision,
        "alembic_head": head_revision(),
        "postgres": postgres,
        "raw_storage": raw_storage,
        "portraits": portraits,
        "database_name": identity.get("database"),
        "database_host": identity.get("host"),
    }
    if not manifest_is_safe(payload):
        raise BackupError("manifest would contain a secret; refusing to write")
    return payload


def write_manifest(path: Path, payload: Mapping[str, object]) -> None:
    if not manifest_is_safe(payload):
        raise BackupError("manifest would contain a secret; refusing to write")
    refuse_overwrite(path)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    restrict_file(path)
