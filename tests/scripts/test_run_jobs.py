from backend.app.core.config import get_settings
from backend.app.jobs.catalog import JOB_CATALOG, JobSpec
from backend.app.schemas.jobs import IngestionJobMetrics
from scripts.run_jobs import main, parse_args


def test_manual_job_cli_accepts_supported_jobs():
    for name in JOB_CATALOG:
        assert parse_args([name]).job == name


def test_manual_job_cli_supports_history_list():
    args = parse_args(["list", "--limit", "5"])
    assert args.job == "list"
    assert args.limit == 5


def test_manual_job_cli_runs_and_lists_history(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'cli-jobs.db'}"
    monkeypatch.setenv("VERAPOLITICA_DATABASE_URL", database_url)
    monkeypatch.setenv("VERAPOLITICA_RAW_STORAGE_PATH", str(tmp_path / "raw"))
    get_settings.cache_clear()

    def fake_runner(settings, session_factory):
        del settings, session_factory
        return IngestionJobMetrics(records_processed=2, records_created=1)

    catalog = {
        "senato": JobSpec(
            "senato",
            "senato-repubblica",
            fake_runner,
            "schedule_senato_cron",
        )
    }
    monkeypatch.setattr("backend.app.jobs.service.JOB_CATALOG", catalog)
    try:
        assert main(["senato"]) == 0
        assert main(["list"]) == 0
    finally:
        get_settings.cache_clear()
