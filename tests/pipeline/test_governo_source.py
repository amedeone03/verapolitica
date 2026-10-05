import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

from backend.app.models import RawDocument, Source
from backend.app.pipeline.collectors import CollectedDocument, GovernoCollector
from backend.app.pipeline.ingestion_pipeline import IngestionPipeline
from backend.app.pipeline.mappers import GovernoCandidateProfileMapper
from backend.app.pipeline.parsers import GovernoParser
from backend.app.schemas import SourceDocumentProvenance


FIXTURE_PATH = Path("data/fixtures/governo/governo_office_holders.json")


def fixture_bundle() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


def fixture_content(*, pretty=False, reverse=False) -> bytes:
    bundle = fixture_bundle()
    if reverse:
        bundle["profiles"].reverse()
    return json.dumps(
        bundle,
        ensure_ascii=False,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
    ).encode()


def governo_source(session_factory) -> Source:
    with session_factory() as session:
        source = Source(
            key="governo-italiano",
            name="Governo Italiano",
            base_url="https://www.governo.it",
        )
        session.add(source)
        session.commit()
        return source


class SequenceCollector:
    version = "governo_collector_v1"

    def __init__(self, documents: list[bytes]) -> None:
        self.documents = iter(documents)
        self.count = 0

    def collect(self) -> CollectedDocument:
        content = next(self.documents)
        retrieved_at = datetime(2026, 10, 3, tzinfo=timezone.utc) + timedelta(
            seconds=self.count
        )
        self.count += 1
        return CollectedDocument(
            content=content,
            source_url="https://www.governo.it/it/ministri-e-sottosegretari",
            content_type="application/vnd.verapolitica.governo-bundle+json",
            retrieved_at=retrieved_at,
            collector_version=self.version,
        )


def test_collector_fetches_index_and_current_profile_pages():
    bundle = fixture_bundle()
    pages = {item["url"]: item["html"] for item in bundle["profiles"]}

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == bundle["index_url"]:
            return httpx.Response(200, text=bundle["index_html"])
        return httpx.Response(200, text=pages[str(request.url)])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        document = GovernoCollector(bundle["index_url"], client=client).collect()

    collected = json.loads(document.content)
    assert document.collector_version == "governo_collector_v1"
    assert document.source_url == bundle["index_url"]
    assert [item["url"] for item in collected["profiles"]] == sorted(pages)
    assert len(collected["profiles"]) == 4


def test_parser_extracts_roles_births_identifiers_and_incomplete_identity():
    parsed = GovernoParser().parse(fixture_content())

    assert parsed.parser_version == "governo_parser_v1"
    assert len(parsed.structured_records) == 4
    records = {record["display_name"]: record for record in parsed.structured_records}
    mario = records["Mario Rossi"]
    assert mario["birth_date"] == "1970-01-01"
    assert mario["birth_city"] == "Roma"
    assert mario["source_identifiers"] == ["https://www.governo.it/it/node/4001"]
    assert mario["mandates"][0]["office"] == "Presidente del Consiglio"
    assert mario["mandates"][0]["mandate_start"] == "2022-10-22"
    assert records["Lucia Bianchi"]["mandates"][0]["office"] == (
        "Ministro senza portafoglio"
    )
    assert records["Anna Neri"]["mandates"][0]["office"] == "Viceministro"
    assert records["Carlo Verdi"]["birth_date"] is None


def test_parser_canonicalization_ignores_bundle_order_and_json_formatting():
    first = GovernoParser().parse(fixture_content())
    second = GovernoParser().parse(fixture_content(pretty=True, reverse=True))

    assert first.canonical_json == second.canonical_json
    assert first.structured_records == second.structured_records


def test_mapper_outputs_generic_profile_and_exact_page_provenance():
    record = next(
        record
        for record in GovernoParser().parse(fixture_content()).structured_records
        if record["display_name"] == "Mario Rossi"
    )
    provenance = SourceDocumentProvenance(
        source_key="governo-italiano",
        raw_document_id=42,
        source_url="https://www.governo.it/it/ministri-e-sottosegretari",
        retrieved_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
        raw_sha256="a" * 64,
        normalized_sha256="b" * 64,
        collector_version="governo_collector_v1",
        parser_version="governo_parser_v1",
    )

    candidate = GovernoCandidateProfileMapper().map_records(
        (record,), document=provenance
    )[0]

    assert candidate.identity.given_name == "Mario"
    assert candidate.identity.family_name == "Rossi"
    assert candidate.identity.birth_date == date(1970, 1, 1)
    assert candidate.identity.source_identifiers[0].authority == "governo-italiano"
    assert candidate.profile.profession is None
    assert candidate.profile.mandates[0].institution == (
        "Presidenza del Consiglio dei Ministri"
    )
    assert candidate.profile.mandates[0].legislature == "Governo Meloni"
    birth_field = next(
        field
        for field in candidate.provenance.fields
        if field.target_path == "identity.birth_date"
    )
    assert str(birth_field.source_url).endswith("/mario-rossi")
    assert birth_field.source_field == "biography.birth_date"


def test_multiple_profile_identifiers_retain_their_exact_page_provenance():
    bundle = fixture_bundle()
    second_page = dict(bundle["profiles"][1])
    second_page["url"] = (
        "https://www.governo.it/it/governo/meloni/ministro/mario-rossi"
    )
    second_page["html"] = second_page["html"].replace(
        "/presidente-del-consiglio/mario-rossi",
        "/ministro/mario-rossi",
    ).replace("/it/node/4001", "/it/node/4999")
    bundle["profiles"].append(second_page)
    record = next(
        record
        for record in GovernoParser()
        .parse(json.dumps(bundle, ensure_ascii=False).encode())
        .structured_records
        if record["display_name"] == "Mario Rossi"
    )
    provenance = SourceDocumentProvenance(
        source_key="governo-italiano",
        raw_document_id=42,
        source_url=bundle["index_url"],
        retrieved_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
        raw_sha256="a" * 64,
        normalized_sha256="b" * 64,
        collector_version="governo_collector_v1",
        parser_version="governo_parser_v1",
    )

    candidate = GovernoCandidateProfileMapper().map_records(
        (record,), document=provenance
    )[0]
    identifier_evidence = {
        field.source_value: str(field.source_url)
        for field in candidate.provenance.fields
        if field.source_field == "link[rel=shortlink]"
    }

    assert identifier_evidence == {
        "https://www.governo.it/it/node/4001": (
            "https://www.governo.it/it/governo/meloni/presidente-del-consiglio/"
            "mario-rossi"
        ),
        "https://www.governo.it/it/node/4999": (
            "https://www.governo.it/it/governo/meloni/ministro/mario-rossi"
        ),
    }


def test_governo_normalized_change_detection_and_changed_only_candidates(
    session_factory, raw_storage
):
    source = governo_source(session_factory)
    original = fixture_content()
    formatting_only = fixture_content(pretty=True, reverse=True)
    changed_bundle = fixture_bundle()
    changed_bundle["profiles"][0]["html"] = changed_bundle["profiles"][0][
        "html"
    ].replace("Ministero della Salute", "Ministero dell'Interno")
    changed = json.dumps(changed_bundle, ensure_ascii=False).encode()
    ingestion = IngestionPipeline(
        session_factory=session_factory,
        storage=raw_storage,
        collector=SequenceCollector([original, formatting_only, changed]),
        parser=GovernoParser(),
        profile_mapper=GovernoCandidateProfileMapper(),
    )

    first = ingestion.run(source_id=source.id, source_key=source.key)
    second = ingestion.run(source_id=source.id, source_key=source.key)
    third = ingestion.run(source_id=source.id, source_key=source.key)

    assert first.change_detected is True
    assert len(first.candidate_profiles) == 4
    assert second.raw_sha256 != first.raw_sha256
    assert second.normalized_sha256 == first.normalized_sha256
    assert second.change_detected is False
    assert second.candidate_profiles == ()
    assert third.change_detected is True
    assert len(third.candidate_profiles) == 4
    with session_factory() as session:
        assert session.query(RawDocument).count() == 3
