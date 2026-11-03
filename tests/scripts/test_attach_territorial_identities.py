from datetime import date

from backend.app.models import RawDocument
from backend.app.schemas import (
    CandidateIdentity,
    CandidateProfile,
    CandidateProfileData,
    CandidateProvenance,
    PoliticalMandate,
    SourceDocumentProvenance,
    SourceIdentifier,
)
from backend.app.services import HumanIdentityResolutionCoordinator
from scripts.attach_governo_identities import Action, plan_attachments
from scripts.attach_territorial_identities import SOURCE_KEY, finish
from tests.pipeline.test_territorial_ingestion import add_document
from tests.services.test_identity_resolution_service import add_politician


def mayor_candidate(document: RawDocument) -> CandidateProfile:
    page = "https://dait.interno.gov.it/elezioni/anagrafe-amministratori/sindaco/roma"
    return CandidateProfile(
        identity=CandidateIdentity(
            display_name="Roberto Gualtieri",
            given_name="Roberto",
            family_name="Gualtieri",
            source_identifiers=(
                SourceIdentifier(authority=SOURCE_KEY, value=page),
            ),
        ),
        profile=CandidateProfileData(
            official_homepage_url=page,
            mandates=(
                PoliticalMandate(
                    institution="Comune di Roma",
                    office="Sindaco",
                    legislature="in carica",
                    mandate_type="Sindaco",
                    start_date=date(2021, 10, 21),
                ),
            ),
        ),
        provenance=CandidateProvenance(
            document=SourceDocumentProvenance(
                source_key=SOURCE_KEY,
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


def test_unique_mayor_name_is_linked(session_factory):
    _source, document_id = add_document(session_factory, SOURCE_KEY, "text/csv")
    politician_id = add_politician(
        session_factory,
        given_name="Roberto",
        family_name="Gualtieri",
        birth_date=date(1966, 7, 22),
    )
    with session_factory() as session:
        incoming = mayor_candidate(session.get(RawDocument, document_id))
    result = HumanIdentityResolutionCoordinator(session_factory).process(incoming)
    assert result.case is not None

    plans = plan_attachments(session_factory, source_key=SOURCE_KEY)
    assert len(plans) == 1
    assert plans[0].action is Action.LINK_EXISTING
    assert plans[0].politician_id == politician_id

    report = finish(session_factory, reviewer="redazione-test", dry_run=False)
    assert [row["display_name"] for row in report.linked] == ["Roberto Gualtieri"]
    assert report.left_pending == []
