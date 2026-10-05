from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.main import create_app
from backend.app.models import (
    ParliamentaryGroup,
    ParliamentaryGroupMembership,
    ParliamentaryGroupSourceIdentifier,
    Politician,
    PoliticianVersion,
    RawDocument,
    RawDocumentStatus,
    Source,
)
from backend.app.schemas import PoliticalMandate, PoliticianVersionProfile
from backend.app.services import normalize_person_name


@dataclass
class PublicAPIContext:
    client: TestClient
    unpublished_id: int
    published_id: int
    pointer_test_id: int
    pointer_version_number: int


def profile(given_name: str, *, profession: str) -> PoliticianVersionProfile:
    return PoliticianVersionProfile(
        given_name=given_name,
        family_name="Rossi",
        birth_date=date(1970, 1, 2),
        birth_place=None,
        gender=None,
        profession=profession,
        image_url=None,
        official_homepage_url=None,
        mandates=(
            PoliticalMandate(
                institution="Senato della Repubblica",
                office="senator",
                legislature="19",
                mandate_type="elettivo",
                start_date=date(2022, 10, 13),
            ),
        ),
    )


def add_politician(session, given_name: str) -> Politician:
    politician = Politician(
        canonical_given_name=given_name,
        canonical_family_name="Rossi",
        normalized_name=normalize_person_name(given_name, "Rossi"),
        birth_date=date(1970, 1, 2),
    )
    session.add(politician)
    session.flush()
    return politician


@pytest.fixture
def public_api_context(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'public-api.db'}"
    settings = Settings(
        database_url=database_url,
        raw_storage_path=tmp_path / "raw",
        admin_api_key="test-admin-secret",
        admin_reviewer_identity="api-editor",
    )
    engine = create_db_engine(database_url)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    published_at = datetime(2026, 10, 2, 10, tzinfo=timezone.utc)

    with factory() as session:
        unpublished = add_politician(session, "Unpublished")

        published = add_politician(session, "Published")
        published_profile = profile("Published", profession="Avvocata")
        published_version = PoliticianVersion(
            politician_id=published.id,
            version_number=1,
            profile_schema_version=1,
            profile_data=published_profile.model_dump(mode="json"),
            published_at=published_at,
        )
        session.add(published_version)
        session.flush()
        published.current_version_id = published_version.id

        source = Source(
            key="senato-repubblica",
            name="Senato della Repubblica",
            base_url="https://dati.senato.it",
        )
        session.add(source)
        session.flush()
        document = RawDocument(
            source_id=source.id,
            retrieved_at=published_at,
            source_url="https://dati.senato.it/sparql",
            content_type="application/json",
            storage_key="senato/groups.json",
            raw_sha256="a" * 64,
            normalized_sha256="b" * 64,
            structured_records=[],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="senato_collector_v2",
            parser_version="senato_parser_v2",
        )
        current_group = ParliamentaryGroup(
            canonical_name="Fratelli d'Italia",
            abbreviation="FdI",
            institution="Senato della Repubblica",
            legislature="19",
        )
        previous_group = ParliamentaryGroup(
            canonical_name="Gruppo precedente",
            abbreviation="GP",
            institution="Senato della Repubblica",
            legislature="19",
        )
        session.add_all((document, current_group, previous_group))
        session.flush()
        session.add_all(
            (
                ParliamentaryGroupSourceIdentifier(
                    parliamentary_group_id=current_group.id,
                    source_id=source.id,
                    value="https://dati.senato.it/gruppo/85",
                    legislature="19",
                ),
                ParliamentaryGroupSourceIdentifier(
                    parliamentary_group_id=previous_group.id,
                    source_id=source.id,
                    value="https://dati.senato.it/gruppo/84",
                    legislature="19",
                ),
                ParliamentaryGroupMembership(
                    politician_id=published.id,
                    parliamentary_group_id=current_group.id,
                    source_id=source.id,
                    raw_document_id=document.id,
                    identity_key="c" * 64,
                    source_url="https://dati.senato.it/senatore/public",
                    start_date=date(2024, 2, 1),
                    role="Membro",
                ),
                ParliamentaryGroupMembership(
                    politician_id=published.id,
                    parliamentary_group_id=previous_group.id,
                    source_id=source.id,
                    raw_document_id=document.id,
                    identity_key="d" * 64,
                    source_url="https://dati.senato.it/senatore/public",
                    start_date=date(2022, 10, 18),
                    end_date=date(2024, 1, 31),
                    role="Membro",
                ),
            )
        )

        pointer_test = add_politician(session, "Current")
        current_profile = profile("Current", profession="Current pointer")
        later_profile = profile("Wrong", profession="Higher version number")
        current_version = PoliticianVersion(
            politician_id=pointer_test.id,
            version_number=1,
            profile_schema_version=1,
            profile_data=current_profile.model_dump(mode="json"),
            published_at=published_at,
        )
        later_version = PoliticianVersion(
            politician_id=pointer_test.id,
            version_number=2,
            profile_schema_version=1,
            profile_data=later_profile.model_dump(mode="json"),
            published_at=published_at + timedelta(hours=1),
        )
        session.add_all((current_version, later_version))
        session.flush()
        pointer_test.current_version_id = current_version.id
        session.commit()

        ids = (
            unpublished.id,
            published.id,
            pointer_test.id,
            current_version.version_number,
        )

    app = create_app(settings)
    with TestClient(app) as client:
        yield PublicAPIContext(client, *ids)
    engine.dispose()


def test_list_excludes_politician_without_current_version(public_api_context):
    response = public_api_context.client.get("/politicians")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert public_api_context.unpublished_id not in {
        item["id"] for item in payload["items"]
    }


def test_list_includes_published_current_version_without_auth(public_api_context):
    response = public_api_context.client.get("/politicians?offset=0&limit=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["offset"] == 0
    assert payload["limit"] == 1
    assert len(payload["items"]) == 1


def test_detail_returns_current_published_profile(public_api_context):
    response = public_api_context.client.get(
        f"/politicians/{public_api_context.published_id}"
    )

    assert response.status_code == 200
    assert response.json()["profile"]["profession"] == "Avvocata"
    assert response.json()["current_version_number"] == 1


def test_detail_returns_current_then_historical_parliamentary_groups(
    public_api_context,
):
    response = public_api_context.client.get(
        f"/politicians/{public_api_context.published_id}"
    )

    assert response.status_code == 200
    memberships = response.json()["parliamentary_groups"]
    assert [item["name"] for item in memberships] == [
        "Fratelli d'Italia",
        "Gruppo precedente",
    ]
    assert memberships[0]["end_date"] is None
    assert memberships[0]["source"] == {
        "name": "Senato della Repubblica",
        "url": "https://dati.senato.it/senatore/public",
    }
    assert memberships[1]["end_date"] == "2024-01-31"
    serialized = str(memberships)
    assert "parliamentary_group_id" not in serialized
    assert "identity_key" not in serialized


@pytest.mark.parametrize("identifier", ["unpublished_id", None])
def test_detail_returns_404_without_public_profile(public_api_context, identifier):
    politician_id = (
        getattr(public_api_context, identifier) if identifier is not None else 999_999
    )
    response = public_api_context.client.get(f"/politicians/{politician_id}")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "published politician not found",
            "details": None,
        }
    }


def test_detail_uses_current_pointer_not_max_version(public_api_context):
    response = public_api_context.client.get(
        f"/politicians/{public_api_context.pointer_test_id}"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["given_name"] == "Current"
    assert payload["profile"]["profession"] == "Current pointer"
    assert payload["current_version_number"] == public_api_context.pointer_version_number


def test_public_response_excludes_editorial_metadata(public_api_context):
    response = public_api_context.client.get(
        f"/politicians/{public_api_context.published_id}"
    )

    assert response.status_code == 200
    serialized = response.text.casefold()
    for internal_name in (
        "draft",
        "review",
        "reviewer",
        "evidence",
        "raw_document",
        "storage_key",
        "normalized_sha256",
    ):
        assert internal_name not in serialized


def test_admin_endpoints_remain_protected(public_api_context):
    response = public_api_context.client.get("/admin/drafts")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_public_pagination_is_validated(public_api_context):
    response = public_api_context.client.get("/politicians?limit=0")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
