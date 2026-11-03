import hashlib
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import (
    ParliamentaryGroupMembership,
    Politician,
    PoliticianSourceIdentifier,
    RawDocument,
    RawDocumentStatus,
    Source,
)
from backend.app.pipeline.collectors.base import encode_sparql_bundle
from backend.app.services import normalize_person_name
from backend.app.storage import LocalRawStorage
from scripts.reprocess_parliamentary_groups import reprocess


def test_reprocess_attaches_groups_from_the_stored_camera_bundle(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'groups.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    storage = LocalRawStorage(tmp_path / "raw")
    bundle = encode_sparql_bundle(
        schema="verapolitica_camera_bundle_v1",
        people_response=Path("data/fixtures/camera/camera_deputies.json").read_bytes(),
        parliamentary_groups_response=Path("data/fixtures/camera/camera_groups.json").read_bytes(),
    )
    digest = hashlib.sha256(bundle).hexdigest()
    storage_key = storage.put("camera-deputati", digest, bundle)
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    with factory() as session:
        source = Source(
            key="camera-deputati",
            name="Camera dei Deputati",
            base_url="https://dati.camera.it",
        )
        session.add(source)
        session.flush()
        document = RawDocument(
            source_id=source.id,
            retrieved_at=now,
            source_url="https://dati.camera.it/sparql",
            content_type="application/json",
            storage_key=storage_key,
            raw_sha256=digest,
            process_status=RawDocumentStatus.PARSED,
            collector_version="camera_collector_v2",
            parser_version="camera_parser_v2",
        )
        politician = Politician(
            canonical_given_name="Maria",
            canonical_family_name="Rossi",
            normalized_name=normalize_person_name("Maria", "Rossi"),
            birth_date=date(1970, 1, 2),
        )
        session.add_all((document, politician))
        session.flush()
        session.add(
            PoliticianSourceIdentifier(
                politician_id=politician.id,
                source_id=source.id,
                value="http://dati.camera.it/ocd/deputato.rdf/d100_19",
            )
        )
        session.commit()
        politician_id = politician.id

    dry = reprocess(factory, storage, source_keys=("camera-deputati",), dry_run=True)
    assert dry.sources[0].total_observations == 1
    assert dry.sources[0].memberships_created == 0

    applied = reprocess(factory, storage, source_keys=("camera-deputati",), dry_run=False)
    assert applied.sources[0].memberships_created == 1
    assert applied.sources[0].unresolved_references == 0
    with factory() as session:
        membership = session.scalar(
            select(ParliamentaryGroupMembership).where(
                ParliamentaryGroupMembership.politician_id == politician_id
            )
        )
        assert membership is not None
        assert membership.start_date == date(2022, 10, 18)
        assert session.scalar(select(func.count()).select_from(ParliamentaryGroupMembership)) == 1
    engine.dispose()
