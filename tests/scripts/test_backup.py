from __future__ import annotations

import json
import os
import stat
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.app.core.config import AppEnvironment, Settings
from scripts.backup_ops import (
    BackupError,
    archive_directory,
    argv_contains_secret,
    build_manifest,
    extract_archive,
    manifest_is_safe,
    manifest_name,
    pg_dump_argv,
    pg_restore_argv,
    postgres_dump_name,
    prepare_output_dir,
    raw_archive_name,
    refuse_demo_path,
    refuse_overwrite,
    require_confirmation,
    require_custom_dump,
    require_postgresql_url,
    restore_postgres,
    utc_stamp,
    write_manifest,
)
from scripts.backup_postgres import main as backup_main
from scripts.backup_postgres import parse_args as parse_backup_args
from scripts.restore_postgres import main as restore_main
from scripts.restore_postgres import parse_args as parse_restore_args

REPO_ROOT = Path(__file__).resolve().parents[2]
SECRET_URL = "postgresql+psycopg://vp:s3cret-pass@db.example:5432/verapolitica"


@pytest.fixture
def pg_bins(monkeypatch):
    monkeypatch.setattr(
        "scripts.backup_ops.find_pg_binary", lambda name: f"/usr/bin/{name}"
    )


def test_timestamped_backup_filenames():
    stamp = utc_stamp(datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc))
    assert stamp == "20261016T120000Z"
    assert postgres_dump_name(stamp) == "verapolitica-postgres-20261016T120000Z.dump"
    assert raw_archive_name(stamp) == "verapolitica-raw-20261016T120000Z.tar.gz"
    assert manifest_name(stamp) == "verapolitica-backup-20261016T120000Z.json"
    with pytest.raises(BackupError, match="timestamp"):
        postgres_dump_name("../escape")


def test_pg_dump_and_restore_argv_omit_password(pg_bins, tmp_path):
    dump = tmp_path / "verapolitica.dump"
    dump_argv = pg_dump_argv(SECRET_URL, dump)
    restore_argv = pg_restore_argv(SECRET_URL, dump, replace_existing=True)
    assert "-Fc" in dump_argv
    assert "--no-password" in dump_argv
    assert dump_argv[-1] != "s3cret-pass"
    assert "s3cret-pass" not in " ".join(dump_argv)
    assert "s3cret-pass" not in " ".join(restore_argv)
    assert argv_contains_secret(dump_argv, SECRET_URL) is False
    assert "--clean" in restore_argv
    assert "--if-exists" in restore_argv
    assert "--no-owner" in restore_argv


def test_sqlite_and_demo_paths_are_rejected(tmp_path):
    with pytest.raises(BackupError, match="SQLite"):
        require_postgresql_url("sqlite:///./data/verapolitica.db")
    demo = tmp_path / "data" / "demo" / "raw"
    demo.mkdir(parents=True)
    with pytest.raises(BackupError, match="demo"):
        refuse_demo_path(demo, label="RAW_STORAGE_PATH")


def test_restore_requires_explicit_confirmation():
    with pytest.raises(BackupError, match="--yes"):
        require_confirmation(confirmed=False, action="postgres restore")
    require_confirmation(confirmed=True, action="postgres restore")


def test_restore_refuses_invalid_dump(tmp_path):
    missing = tmp_path / "missing.dump"
    with pytest.raises(BackupError, match="missing or empty"):
        require_custom_dump(missing)
    sql = tmp_path / "plain.sql"
    sql.write_text("CREATE TABLE x();", encoding="utf-8")
    with pytest.raises(BackupError, match="custom-format"):
        require_custom_dump(sql)
    empty = tmp_path / "empty.dump"
    empty.write_bytes(b"")
    with pytest.raises(BackupError, match="missing or empty"):
        require_custom_dump(empty)
    garbage = tmp_path / "garbage.dump"
    garbage.write_bytes(b"SQLite format 3\x00")
    with pytest.raises(BackupError, match="custom-format"):
        require_custom_dump(garbage)


def test_restore_refuses_nonempty_database_without_replace(monkeypatch, tmp_path, pg_bins):
    dump = tmp_path / "ok.dump"
    dump.write_bytes(b"PGDMP" + b"\x00" * 16)
    monkeypatch.setattr("scripts.backup_ops.public_table_count", lambda url: 4)
    with pytest.raises(BackupError, match="not empty"):
        restore_postgres(SECRET_URL, dump, confirmed=True, replace_existing=False)
    with pytest.raises(BackupError, match="--yes"):
        restore_postgres(SECRET_URL, dump, confirmed=False, replace_existing=True)


def test_backup_refuses_silent_overwrite(tmp_path):
    existing = tmp_path / "verapolitica-postgres-20261016T120000Z.dump"
    existing.write_bytes(b"PGDMP")
    with pytest.raises(BackupError, match="overwrite"):
        refuse_overwrite(existing)


def test_output_dir_permissions_and_manifest_safety(tmp_path):
    output = prepare_output_dir(tmp_path / "backups")
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    payload = build_manifest(
        stamp="20261016T120000Z",
        environment="production",
        alembic_revision="e2b8f6c03d41",
        postgres={
            "filename": "verapolitica-postgres-20261016T120000Z.dump",
            "bytes": 12,
            "sha256": "abc",
            "database": "verapolitica",
            "host": "db",
            "format": "custom",
        },
        raw_storage={
            "filename": "verapolitica-raw-20261016T120000Z.tar.gz",
            "bytes": 4,
            "sha256": "def",
            "file_count": 1,
        },
    )
    assert manifest_is_safe(payload)
    assert "s3cret" not in json.dumps(payload)
    assert "password" not in json.dumps(payload).casefold()
    path = output / "manifest.json"
    write_manifest(path, payload)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(BackupError, match="secret"):
        build_manifest(
            stamp="20261016T120000Z",
            environment="production",
            alembic_revision="e2b8f6c03d41",
            postgres={"filename": "x.dump", "password": "nope"},
            raw_storage=None,
        )


def test_raw_archive_excludes_env_files(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "kept.bin").write_bytes(b"provenance")
    (raw / ".env").write_text("VERAPOLITICA_ADMIN_API_KEY=super-secret", encoding="utf-8")
    (raw / ".env.production").write_text("PASSWORD=nope", encoding="utf-8")
    dest = tmp_path / "backups"
    dest.mkdir()
    archive = dest / "raw.tar.gz"
    count = archive_directory(raw, archive, label="RAW_STORAGE_PATH")
    assert count == 1
    extracted = tmp_path / "restored"
    extract_archive(
        archive,
        extracted,
        confirmed=True,
        replace_existing=False,
        label="raw storage",
    )
    names = {path.name for path in extracted.rglob("*") if path.is_file()}
    assert names == {"kept.bin"}
    assert (extracted / "kept.bin").read_bytes() == b"provenance"
    with tarfile.open(archive, "r:gz") as handle:
        blob = " ".join(handle.getnames())
    assert ".env" not in blob
    with pytest.raises(BackupError, match="not empty"):
        extract_archive(
            archive,
            extracted,
            confirmed=True,
            replace_existing=False,
            label="raw storage",
        )


def test_extract_archive_requires_yes_and_targz(tmp_path):
    archive = tmp_path / "raw.zip"
    archive.write_bytes(b"not-tar")
    with pytest.raises(BackupError, match="--yes"):
        extract_archive(
            archive,
            tmp_path / "out",
            confirmed=False,
            replace_existing=False,
            label="raw storage",
        )
    with pytest.raises(BackupError, match="tar.gz"):
        extract_archive(
            archive,
            tmp_path / "out",
            confirmed=True,
            replace_existing=False,
            label="raw storage",
        )


def test_backup_cli_writes_secret_free_manifest(monkeypatch, tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "doc.bin").write_bytes(b"raw-bytes")
    settings = Settings(
        env=AppEnvironment.TEST,
        database_url=SECRET_URL,
        raw_storage_path=raw,
        admin_api_key="test-admin-secret",
    )
    monkeypatch.setattr("scripts.backup_postgres.get_settings", lambda: settings)
    monkeypatch.setattr(
        "scripts.backup_postgres.read_alembic_revision",
        lambda url: "e2b8f6c03d41",
    )

    def fake_dump(url: str, destination: Path) -> None:
        assert url == SECRET_URL
        destination.write_bytes(b"PGDMP" + b"\x00" * 24)
        os.chmod(destination, stat.S_IRUSR | stat.S_IWUSR)

    monkeypatch.setattr("scripts.backup_postgres.dump_postgres", fake_dump)
    output = tmp_path / "backups"
    assert backup_main(["--output-dir", str(output)]) == 0
    dumps = list(output.glob("*.dump"))
    manifests = list(output.glob("*.json"))
    archives = list(output.glob("*.tar.gz"))
    assert len(dumps) == 1
    assert len(manifests) == 1
    assert len(archives) == 1
    payload = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert payload["alembic_revision"] == "e2b8f6c03d41"
    assert payload["app"] == "verapolitica"
    blob = manifests[0].read_text(encoding="utf-8")
    assert "s3cret-pass" not in blob
    assert "postgresql+psycopg://" not in blob
    assert "admin_api_key" not in blob
    assert parse_backup_args([]).output_dir == Path("backups")


def test_backup_cli_refuses_sqlite(monkeypatch, tmp_path):
    settings = Settings(
        env=AppEnvironment.TEST,
        database_url=f"sqlite:///{tmp_path / 'local.db'}",
        raw_storage_path=tmp_path / "raw",
        admin_api_key="test-admin-secret",
    )
    monkeypatch.setattr("scripts.backup_postgres.get_settings", lambda: settings)
    assert backup_main(["--output-dir", str(tmp_path / "backups")]) == 1


def test_restore_cli_safeguards(monkeypatch, tmp_path):
    dump = tmp_path / "ok.dump"
    dump.write_bytes(b"PGDMP" + b"\x00" * 16)
    settings = Settings(
        env=AppEnvironment.TEST,
        database_url=SECRET_URL,
        raw_storage_path=tmp_path / "raw",
        admin_api_key="test-admin-secret",
    )
    monkeypatch.setattr("scripts.restore_postgres.get_settings", lambda: settings)
    assert restore_main(["--dump", str(dump)]) == 1
    assert restore_main(["--dump", str(dump), "--replace-existing"]) == 1
    sql = tmp_path / "not.dump.sql"
    sql.write_text("SELECT 1;", encoding="utf-8")
    assert restore_main(["--dump", str(sql), "--yes"]) == 1
    args = parse_restore_args(["--dump", str(dump), "--yes"])
    assert args.yes is True
    assert args.replace_existing is False


def test_backup_directories_are_gitignored():
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "backups/" in gitignore
    assert "*.dump" in gitignore
    dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "backups" in dockerignore
    completed = subprocess.run(
        ["git", "check-ignore", "backups/example.dump", "backups/raw.tar.gz"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert "backups/example.dump" in completed.stdout
