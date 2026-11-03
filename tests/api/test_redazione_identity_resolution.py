from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.main import create_app
from backend.app.models import (
    IdentityResolutionCase,
    Politician,
    PoliticianSourceIdentifier,
    RawDocument,
    RawDocumentStatus,
    Source,
)
from backend.app.schemas import (
    CandidateIdentity,
    CandidateProfile,
    CandidateProfileData,
    CandidateProvenance,
    NewMatchReason,
    NewResult,
    PoliticalMandate,
    SourceDocumentProvenance,
    SourceIdentifier,
)
from backend.app.services import IdentityResolutionService, normalize_person_name


ANNA = {"Authorization": "Bearer tok-anna-redattrice"}
BRUNO = {"Authorization": "Bearer tok-bruno-verificatore"}
MEMBERS = (
    "Anna Redattrice=tok-anna-redattrice;Bruno Verificatore=tok-bruno-verificatore"
)


def make_candidate(document: RawDocument, sequence: int) -> CandidateProfile:
    return CandidateProfile(
        identity=CandidateIdentity(
            display_name="Antonio Example",
            given_name="Antonio",
            family_name="Example",
            source_identifiers=(
                SourceIdentifier(
                    authority="governo-italiano",
                    value=f"https://www.governo.it/it/node/{9100 + sequence}",
                ),
            ),
        ),
        profile=CandidateProfileData(
            official_homepage_url=f"https://www.governo.it/it/governo/example/antonio-{sequence}",
            mandates=(
                PoliticalMandate(
                    institution="Governo Italiano",
                    office="Sottosegretario",
                    legislature="Governo Meloni",
                    mandate_type="Sottosegretario di Stato",
                    start_date=date(2022, 10, 31),
                ),
            ),
        ),
        provenance=CandidateProvenance(
            document=SourceDocumentProvenance(
                source_key="governo-italiano",
                raw_document_id=document.id,
                source_url=document.source_url,
                retrieved_at=document.retrieved_at,
                raw_sha256=document.raw_sha256,
                normalized_sha256=document.normalized_sha256,
                collector_version=document.collector_version,
                parser_version=document.parser_version,
            ),
            fields=(),
        ),
    )


@pytest.fixture
def identity_console(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'redazione-identita.db'}"
    settings = Settings(
        database_url=database_url,
        raw_storage_path=tmp_path / "raw",
        redazione_members=MEMBERS,
    )
    engine = create_db_engine(database_url)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        source = Source(
            key="governo-italiano",
            name="Governo Italiano",
            base_url="https://www.governo.it",
        )
        session.add(source)
        session.flush()
        document = RawDocument(
            source_id=source.id,
            retrieved_at=datetime(2026, 10, 5, tzinfo=timezone.utc),
            source_url="https://www.governo.it/it/ministri-e-sottosegretari",
            content_type="application/vnd.verapolitica.governo-bundle+json",
            storage_key="governo/redazione-cases.json",
            raw_sha256="c" * 64,
            normalized_sha256="d" * 64,
            structured_records=[],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="governo_collector_v1",
            parser_version="governo_parser_v1",
        )
        session.add(document)
        politician = Politician(
            canonical_given_name="Antonio",
            canonical_family_name="Example",
            normalized_name=normalize_person_name("Antonio", "Example"),
            birth_date=date(1970, 1, 1),
        )
        session.add(politician)
        session.commit()
        existing_id = politician.id
        document_id = document.id

    with factory() as session:
        document = session.get(RawDocument, document_id)
        service = IdentityResolutionService(factory)
        case_ids = tuple(
            service.create_or_reuse_case(
                make_candidate(document, sequence),
                NewResult(reason=NewMatchReason.INSUFFICIENT_FALLBACK_IDENTITY),
            ).case_id
            for sequence in range(1, 3)
        )
    app = create_app(settings)
    with TestClient(app) as client:
        yield client, factory, case_ids, existing_id
    engine.dispose()


def test_identity_queue_is_redazione_only(identity_console):
    client, _factory, _case_ids, _existing = identity_console
    missing = client.get("/redazione/api/identita")
    invalid = client.get(
        "/redazione/api/identita",
        headers={"Authorization": "Bearer wrong"},
    )
    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_redazione_lists_and_links_with_the_member_name(identity_console):
    client, factory, case_ids, existing_id = identity_console
    overview = client.get("/redazione/api/panoramica", headers=ANNA)
    listing = client.get("/redazione/api/identita?status=pending", headers=ANNA)
    detail = client.get(f"/redazione/api/identita/{case_ids[0]}", headers=ANNA)

    assert overview.status_code == 200
    assert overview.json()["pending_identities"] == 2
    assert listing.status_code == 200
    assert listing.json()["total"] == 2
    assert detail.status_code == 200
    assert detail.json()["official_source_url"].startswith("https://www.governo.it/")

    linked = client.post(
        f"/redazione/api/identita/{case_ids[0]}/collega",
        headers=ANNA,
        json={"politician_id": existing_id, "note": "Stesso nome ufficiale"},
    )
    created = client.post(
        f"/redazione/api/identita/{case_ids[1]}/nuova",
        headers=BRUNO,
        json={"note": "Nome unico sulla pagina governo.it"},
    )
    assert linked.status_code == 200
    assert linked.json()["status"] == "resolved_existing"
    assert linked.json()["reviewer_identity"] == "Anna Redattrice"
    assert created.status_code == 200
    assert created.json()["status"] == "resolved_new"
    assert created.json()["reviewer_identity"] == "Bruno Verificatore"
    with factory() as session:
        case = session.get(IdentityResolutionCase, case_ids[0])
        assert case.reviewer_identity == "Anna Redattrice"
        assert session.scalar(select(func.count()).select_from(PoliticianSourceIdentifier)) >= 1
