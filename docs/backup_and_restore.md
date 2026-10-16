# Backup and restore

This is the operator procedure for backing up and restoring production
PostgreSQL and persistent VeraPolitica files. It is not a VPS bootstrap guide
and it does not enable scheduled jobs.

Keep at least one copy **off the VPS**. A backup that has never been restored
is unverified.

## What is backed up

| Data | Classification | Backup? |
| --- | --- | --- |
| PostgreSQL database | **essential** | yes (`pg_dump -Fc`) |
| `VERAPOLITICA_RAW_STORAGE_PATH` | **essential** (immutable provenance files) | yes (`.tar.gz`) |
| Alembic revision | recorded in the manifest | yes (inside the dump + manifest) |
| Portraits JSON + sibling `portraits/` files | **optional / regenerable** if taken from Governo or Wikimedia | only with `--include-portraits` |
| Portrait download cache | **regenerable/cache** | no |
| Demo uploads (`VERAPOLITICA_DEMO_UPLOAD_PATH`, `data/demo`, `ceo_demo`, `unified_demo`) | **demo-only** | refused |
| Local SQLite files | **demo-only / local** | refused |
| Application logs | **optional / regenerable** | no |
| AI extraction rows | **essential**, stored in PostgreSQL | covered by the database dump |
| AI raw documents | **essential**, stored under raw storage | covered by the raw archive |
| `.env` / `.env.production` | **secrets, not backup data** | excluded from archives; never commit |

Compose named volumes map to the same two essential stores:

- `verapolitica_pg` → PostgreSQL data directory
- `verapolitica_raw` → `/var/lib/verapolitica/raw`

Do not treat `data/demo/`, `data/unified_demo/`, or `data/ceo_demo/` as
production backup sources.

## Prerequisites

- `pg_dump` and `pg_restore` on `PATH` (PostgreSQL 16 client tools)
- `VERAPOLITICA_DATABASE_URL` pointing at PostgreSQL (not SQLite)
- Reachable database host (the production-like compose stack does **not**
  publish port 5432; run the client on the compose network or on the VPS
  host that can reach Postgres)
- Write access to `--output-dir` (default `backups/`, gitignored, mode `0700`)

Passwords travel in `PGPASSWORD` (from `DATABASE_URL`), never on the command
line. Do not hardcode credentials in scripts or documentation.

## Backup

From the repository root, with production env loaded:

```bash
python -m scripts.backup_postgres --output-dir /mnt/offsite/verapolitica
```

This writes timestamped files that are never overwritten:

```text
verapolitica-postgres-YYYYMMDDTHHMMSSZ.dump
verapolitica-raw-YYYYMMDDTHHMMSSZ.tar.gz
verapolitica-backup-YYYYMMDDTHHMMSSZ.json
```

Useful flags:

```bash
# PostgreSQL only (not a complete disaster-recovery backup)
python -m scripts.backup_postgres --output-dir /mnt/offsite/verapolitica --skip-raw

# Include portraits if VERAPOLITICA_PORTRAITS_PATH holds operator-unique files
python -m scripts.backup_postgres --output-dir /mnt/offsite/verapolitica --include-portraits
```

`--output-dir` is the backup destination. Point it at mounted external
storage, an off-server disk, or a staging directory that you later copy to
S3-compatible object storage. This milestone does not integrate a paid cloud
SDK.

The command prints a JSON summary (no DSN, no passwords, no API keys) and
exits non-zero on any failure.

### Compose named volumes

If raw files live only in the `verapolitica_raw` volume, run the backup
client where that path is mounted, or copy the volume to a host directory
first. Example (no cloud provider):

```bash
docker run --rm \
  -v verapolitica_raw:/source:ro \
  -v /mnt/offsite/verapolitica:/dest \
  alpine tar czf /dest/verapolitica-raw-manual.tar.gz -C /source .
```

Prefer `python -m scripts.backup_postgres` when `RAW_STORAGE_PATH` is a real
host path such as `/var/lib/verapolitica/raw`.

## Manifest

Each run writes a JSON manifest next to the dump:

- UTC timestamp
- app name (`verapolitica`) and `VERAPOLITICA_ENV`
- Alembic revision present in the dumped database
- Alembic head of the code that took the backup
- dump/archive filenames, byte sizes, SHA-256 checksums
- database name and host (not user, password, or URL)

Open the manifest before restoring so the dump, raw archive, and schema
revision belong together.

## Restore safeguards

- The target PostgreSQL database **must already exist** (`createdb` or the
  compose `POSTGRES_DB`). This tool never creates or drops the database.
- `--dump` must be a non-empty `pg_dump` custom-format file (`PGDMP` magic).
  Plain `.sql` and SQLite files are refused.
- Restore requires `--yes` or `--force`. There is no implicit confirmation.
- A non-empty public schema is refused unless you also pass
  `--replace-existing` (which adds `pg_restore --clean --if-exists`).
- `--replace-existing` still requires `--yes`.
- Existing dump/archive files are never overwritten on backup.
- Demo/local data paths are refused.
- The database is never dropped.

Create a **new empty database** for disaster recovery whenever possible.
`--replace-existing` is for an isolated restore target you are willing to
overwrite, not for casual use against the live name.

## Restore procedure

### 1. Provision PostgreSQL and an empty database

```bash
createdb verapolitica
# or: createdb verapolitica_restore   # preferred while the old DB still exists
```

Do **not** run `alembic upgrade head` before `pg_restore`. Restoring into a
migrated schema can fail or mix objects. The dump already contains
`alembic_version` and the schema at backup time.

### 2. Restore PostgreSQL (and raw storage in one shot)

Preferred, using the matching files from one manifest:

```bash
python -m scripts.restore_postgres \
  --dump /mnt/offsite/verapolitica/verapolitica-postgres-YYYYMMDDTHHMMSSZ.dump \
  --raw-archive /mnt/offsite/verapolitica/verapolitica-raw-YYYYMMDDTHHMMSSZ.tar.gz \
  --database-url "$VERAPOLITICA_DATABASE_URL" \
  --raw-storage-path /var/lib/verapolitica/raw \
  --yes
```

PostgreSQL only:

```bash
python -m scripts.restore_postgres \
  --dump /mnt/offsite/verapolitica/verapolitica-postgres-YYYYMMDDTHHMMSSZ.dump \
  --database-url "$VERAPOLITICA_DATABASE_URL" \
  --yes
```

### 3. Verify Alembic revision

```bash
python -m alembic current
```

Compare with the manifest `alembic_revision`. Then compare with the **code**
you are about to start:

- If the restored revision **equals** Alembic head: do not migrate.
- If the restored revision is **behind** the new code's head: run
  `python -m alembic upgrade head` **after** restore, using the newer code.
- If the restored revision is **ahead** of the code: deploy matching
  (newer) application code. Never `alembic downgrade` as a data rollback.

### 4. Restore raw storage

```bash
python -m scripts.restore_postgres \
  --raw-archive /mnt/offsite/verapolitica/verapolitica-raw-YYYYMMDDTHHMMSSZ.tar.gz \
  --raw-storage-path /var/lib/verapolitica/raw \
  --yes
```

Extract into an empty volume/directory. `--replace-existing` overwrites
same-named files and does not delete extra files that were not in the
archive.

Postgres and raw archives from the **same backup run** (same timestamp /
manifest) must be restored together.

### 5. Start the app and verify

```bash
python -m scripts.run_web
curl -fsS http://127.0.0.1:8000/health/live
curl -fsS http://127.0.0.1:8000/health/ready
python -m scripts.release_check
python -m scripts.smoke_test --base-url http://127.0.0.1:8000
```

`/health/ready` requires PostgreSQL reachable and Alembic current. Spot-check
row counts for `politicians`, `proposals`, `referendums`,
`ingestion_job_runs`, and `raw_documents` against pre-incident notes.

Do not start the scheduler until a later production step enables it.

## Disaster-recovery order

On a new server (or a replacement VPS disk):

1. Install runtime dependencies and PostgreSQL client tools.
2. Create an empty PostgreSQL database. Do not migrate yet.
3. Restore the `.dump` with `python -m scripts.restore_postgres --dump ... --yes`.
4. Run `python -m alembic current` and confirm it matches the manifest.
5. Restore the matching raw-storage `.tar.gz` into
   `VERAPOLITICA_RAW_STORAGE_PATH`.
6. If and only if the restored schema is behind the **new** code, run
   `python -m alembic upgrade head`.
7. Start web (`python -m scripts.run_web` or the compose `web` service).
8. Confirm `GET /health/live` and `GET /health/ready`.
9. Run `python -m scripts.release_check` and
   `python -m scripts.smoke_test`.

Do not run `prepare_demo`, `reset_unified_demo`, or SQLite `create_all`
against the restored database.

## Retention (manual policy)

No cron or systemd timer is installed in this milestone. Suggested production
policy when you add host scheduling later:

- Take a backup **daily**
- Retain **7 daily** dumps + matching raw archives + manifests
- Retain **4 weekly** copies (for example Sunday dumps)
- Keep **at least one copy off the VPS** (other disk, other server, or later
  S3-compatible storage)
- After a production schema migration, keep the pre-migrate dump until the
  next verified backup

Delete expired files with an operator command; do not overwrite.

## Security

- `backups/` and `*.dump` are gitignored and excluded from the Docker build
  context
- Archives skip `.env*` files if they were misplaced under raw storage
- File mode is `0600` for dump/archive/manifest; output directory is `0700`
- Scripts fail if `pg_dump`/`pg_restore` argv would contain the DB password
- Logs redact PostgreSQL URLs and API keys; backup JSON output omits secrets
- Do not store backups in the web document root or in git

## Verification

After any restore, including a rehearsal on an isolated database:

1. Manifest checksums match the files you restored.
2. `alembic current` matches the manifest revision (then migrate only if
   code is newer).
3. Representative rows survive (at least one known `sources` / politician /
   raw document).
4. Files under `RAW_STORAGE_PATH` match the archive file count.
5. `/health/ready` returns 200.
6. `python -m scripts.smoke_test` is read-only and green.
