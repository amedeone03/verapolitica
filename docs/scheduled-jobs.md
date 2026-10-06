# Scheduled ingestion jobs

Scheduled ingestion is an in-process operator concern. There is no Celery, Redis,
Kafka, or distributed worker pool.

```text
cron / APScheduler
  -> IngestionJobService
  -> existing collector/parser/mapper/service pipeline
  -> IngestionJobRun row
```

Job functions are thin wrappers. Domain services keep their current transaction
and uniqueness rules.

## Job catalog

| Job name | Source key | Pipeline |
| --- | --- | --- |
| `senato` | `senato-repubblica` | politician ingestion + identity + groups |
| `camera` | `camera-deputati` | politician ingestion + identity + groups |
| `governo` | `governo-italiano` | politician ingestion + identity |
| `proposals` | `senato-ddl` | Senato DDL proposal ingestion |
| `territories` | `istat-territories` | ISTAT territorial reference ingestion |
| `territorial-offices` | `dait-current-mayors` | DAIT current-mayor office ingestion |
| `civic-reminders` | `civic-reminders` | Internal reminder-candidate generation for published referendums |

There is no party-ingestion job because no live official affiliation source exists.
`civic-reminders` does not scrape referendum pages and does not send email, SMS, or push.

Existing commands remain valid:

```bash
python -m scripts.run_ingestion --source senato
python -m scripts.run_proposal_ingestion
python -m scripts.run_territorial_ingestion territories --fixture ...
python -m scripts.prepare_demo
```

## Manual job CLI

```bash
python -m scripts.run_jobs senato
python -m scripts.run_jobs camera
python -m scripts.run_jobs governo
python -m scripts.run_jobs proposals
python -m scripts.run_jobs territories
python -m scripts.run_jobs territorial-offices
python -m scripts.run_jobs civic-reminders
python -m scripts.run_jobs list
```

The CLI records `IngestionJobRun` rows with `trigger_type=cli`. A successful run
prints JSON metrics. A failed run persists `status=failed` plus an error summary
and exits `1`. An overlapping active run exits `2`.

## Scheduler

Schedules are disabled unless an environment variable is set. Tests never start
network ingestion automatically.

```bash
export VERAPOLITICA_SCHEDULE_SENATO_CRON="0 3 * * *"
export VERAPOLITICA_SCHEDULE_CAMERA_CRON="15 3 * * *"
export VERAPOLITICA_SCHEDULE_GOVERNO_CRON="30 3 * * *"
export VERAPOLITICA_SCHEDULE_PROPOSALS_CRON="0 4 * * *"
export VERAPOLITICA_SCHEDULE_TERRITORIES_CRON="0 5 * * 0"
export VERAPOLITICA_SCHEDULE_TERRITORIAL_OFFICES_CRON="30 5 * * 0"
export VERAPOLITICA_SCHEDULE_CIVIC_REMINDERS_CRON="0 6 * * *"

python -m scripts.run_scheduler
```

Cron expressions are five-field UTC crontabs consumed by APScheduler. Invalid
expressions are logged and skipped. One failed job does not stop the others.

## Overlap protection

Two identical jobs cannot be `running` at once. The database unique partial index
`uq_ingestion_job_runs_running_name` is the lock. In-memory APScheduler
`max_instances=1` is only a local convenience.

If a process crashes while a row is `running`, the next job start or scheduler
start recovers rows older than `VERAPOLITICA_JOB_STALE_AFTER_MINUTES` (default
60). Recovered rows stay in history as `failed` with `stale_recovered=true`. A
fresh running row still blocks overlap. Do not run two scheduler processes.

Admin job payloads include `duration_ms`, `attempt_count`, and
`stale_recovered` so operators can see failures and recovered stale locks.

## Retries

`VERAPOLITICA_JOB_MAX_RETRIES` defaults to `1` extra attempt.
`VERAPOLITICA_JOB_RETRY_BACKOFF_SECONDS` defaults to `2`.

Retries apply only to transient transport failures (timeouts, connection resets,
HTTP 502/503). Malformed source content and validation errors fail immediately.

## Admin API

Protected by the existing admin bearer token. There is no public job API.

```bash
curl -H "Authorization: Bearer $VERAPOLITICA_ADMIN_API_KEY" \
  http://127.0.0.1:8000/admin/jobs

curl -H "Authorization: Bearer $VERAPOLITICA_ADMIN_API_KEY" \
  http://127.0.0.1:8000/admin/jobs/1

curl -X POST -H "Authorization: Bearer $VERAPOLITICA_ADMIN_API_KEY" \
  http://127.0.0.1:8000/admin/jobs/senato/run
```

Responses include job name, source key, status, timestamps, counts, and a sanitized
error summary. They never include database passwords, API keys, or admin tokens.
