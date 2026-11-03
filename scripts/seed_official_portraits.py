"""Write credited official portraits for published Government holders.

Prefers the institutional ``image_url`` already stored on the published
profile (governo.it / Camera). Does not invent photos. Does not look up
Wikidata unless ``--also-commons`` is set.

    python -m scripts.seed_official_portraits
    python -m scripts.seed_official_portraits --download

Writes ``VERAPOLITICA_PORTRAITS_PATH`` (or ``--portraits-path``). Safe in
production: it only records official source URLs already on the scheda.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sqlalchemy import select

from backend.app.core.config import get_settings
from backend.app.db.schema import prepare_runtime_schema
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import Politician, PoliticianVersion
from backend.app.services.government_offices import has_government_office
from scripts.demo_portraits import (
    build_portraits,
    http_get_bytes,
    http_get_json,
    store_portrait_files,
    write_portraits,
)


@dataclass
class Report:
    portraits: int = 0
    official: int = 0
    commons: int = 0
    warnings: list[str] = field(default_factory=list)
    path: str | None = None


def _published_government(session_factory) -> list[dict]:
    with session_factory() as session:
        rows = session.execute(
            select(Politician, PoliticianVersion)
            .join(PoliticianVersion, PoliticianVersion.id == Politician.current_version_id)
            .where(PoliticianVersion.published_at.is_not(None))
            .order_by(Politician.id)
        ).all()
    people = []
    for politician, version in rows:
        profile = version.profile_data or {}
        if not has_government_office(profile.get("mandates")):
            continue
        people.append(
            {
                "id": politician.id,
                "name": f"{politician.canonical_given_name} {politician.canonical_family_name}",
                "given_name": politician.canonical_given_name,
                "family_name": politician.canonical_family_name,
                "image_url": profile.get("image_url"),
                "source_name": "Fonte ufficiale",
                "source_url": profile.get("official_homepage_url") or profile.get("image_url"),
            }
        )
    return people


def seed(
    session_factory,
    portraits_path: Path,
    *,
    also_commons: bool = False,
    download: bool = False,
    get_json=http_get_json,
    fetch_bytes=http_get_bytes,
) -> Report:
    report = Report(path=str(portraits_path))
    people = _published_government(session_factory)
    portraits = build_portraits(
        people,
        get_json=get_json if also_commons else (lambda url, params: {"search": [], "entities": {}, "query": {"pages": {}}}),
        warnings=report.warnings,
    )
    if not also_commons:
        portraits = {
            key: value
            for key, value in portraits.items()
            if value.get("license") == "Official institutional portrait"
        }
    if download and portraits:
        store_portrait_files(
            portraits,
            portraits_path.parent / "portraits",
            fetch_bytes=fetch_bytes,
            warnings=report.warnings,
        )
    portraits_path.parent.mkdir(parents=True, exist_ok=True)
    write_portraits(portraits_path, portraits)
    report.portraits = len(portraits)
    report.official = sum(
        1 for value in portraits.values() if value.get("license") == "Official institutional portrait"
    )
    report.commons = report.portraits - report.official
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--database-url")
    parser.add_argument("--portraits-path", type=Path)
    parser.add_argument(
        "--also-commons",
        action="store_true",
        help="also accept an unambiguous Wikimedia Commons portrait when no official photo exists",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="store image files next to the JSON so the API does not hot-link",
    )
    args = parser.parse_args(argv)
    settings = get_settings()
    runtime = (
        settings.model_copy(update={"database_url": args.database_url})
        if args.database_url
        else settings
    )
    portraits_path = args.portraits_path or settings.portraits_path
    if portraits_path is None:
        print(json.dumps({"error": "imposta VERAPOLITICA_PORTRAITS_PATH o --portraits-path"}, ensure_ascii=False))
        return 2
    engine = create_db_engine(runtime.database_url)
    try:
        prepare_runtime_schema(engine, runtime)
        report = seed(
            create_session_factory(engine),
            Path(portraits_path),
            also_commons=args.also_commons,
            download=args.download,
        )
    finally:
        engine.dispose()
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
