from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_compose_is_production_like_and_scheduler_is_opt_in():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "env_file:" in compose
    assert ".env.production" in compose
    assert "python -m alembic upgrade head" in compose
    assert "python -m scripts.run_web" in compose
    assert "127.0.0.1:8000:8000" in compose
    assert "verapolitica_raw:/var/lib/verapolitica/raw" in compose
    assert "profiles:" in compose
    assert '"scheduler"' in compose or "- scheduler" in compose
    assert "--reload" not in compose
    assert "prepare_demo" not in compose
    assert "ollama" not in compose.casefold()
    assert "qwen" not in compose.casefold()

    assert "USER verapolitica" in dockerfile
    assert 'CMD ["python", "-m", "scripts.run_web"]' in dockerfile
    assert "/health/live" in dockerfile
    assert "/var/lib/verapolitica/raw" in dockerfile
    assert "chown -R verapolitica:verapolitica /app" not in dockerfile
    assert "privileged" not in compose
    assert "docker.sock" not in compose
    assert "5432:5432" not in compose

    assert "frontend/demo" in dockerignore
    assert "tests" in dockerignore
    assert ".env.*" in dockerignore


def test_production_compose_helper_requires_env_file(tmp_path, monkeypatch):
    script = ROOT / "scripts" / "run_production_compose.sh"
    assert script.is_file()
    text = script.read_text(encoding="utf-8")
    assert ".env.production" in text
    assert "docker compose --env-file" in text
    assert "run_demo" not in text
