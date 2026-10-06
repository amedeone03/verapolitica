from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = REPO_ROOT / "data" / "fixtures" / "ai"


@dataclass(frozen=True, slots=True)
class FakeDemoFixture:
    key: str
    html_path: Path
    response_path: Path
    source_url: str
    source_name: str
    source_key: str
    document_name: str


DEMO_FAKE_FIXTURES: tuple[FakeDemoFixture, ...] = (
    FakeDemoFixture(
        key="ceo-ddl-60476",
        html_path=FIXTURE_DIR / "ceo_ddl_60476.html",
        response_path=FIXTURE_DIR / "ceo_ddl_60476_fake_response.json",
        source_url="https://dati.senato.it/ddl/60476.html",
        source_name="Senato della Repubblica",
        source_key="senato-ddl",
        document_name="ceo_ddl_60476.html",
    ),
)

NO_FIXTURE_MESSAGE = "No deterministic demo extraction fixture exists for this document."


def fixture_digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def match_demo_fixture(content: bytes) -> FakeDemoFixture | None:
    digest = sha256(content).hexdigest()
    for fixture in DEMO_FAKE_FIXTURES:
        if fixture.html_path.is_file() and fixture_digest(fixture.html_path) == digest:
            return fixture
    return None
