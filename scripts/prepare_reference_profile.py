"""Load a reviewed reference-profile fixture into pending editorial drafts.

Never publishes. Never creates pledge assessments. Never overwrites approved
records. Derived fixtures require editorial verification before anything is
public.

  python -m scripts.prepare_reference_profile --dry-run
  python -m scripts.prepare_reference_profile --apply
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import AppEnvironment, Settings, configured_environment, get_settings
from backend.app.db.schema import prepare_sqlite_schema
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import (
    PledgeAssessment,
    Politician,
    PoliticianSourceIdentifier,
    Proposal,
    ProposalActor,
    ProposalActorRole,
    ProposalType,
    RawDocument,
    RawDocumentStatus,
    Source,
)
from backend.app.models.politician_profile import ProfileSourceKind
from backend.app.schemas.politician_profile import (
    BiographyDraftInput,
    CareerEntryDraftInput,
    PositionDraftInput,
    ProceedingDraftInput,
    ProfileSourceInput,
)
from backend.app.schemas.proposal import (
    ObservedActorType,
    ProposalActorObservation,
    ProposalEvidenceObservation,
    ProposalObservation,
)
from backend.app.models import ProposalActorRole as ActorRole
from backend.app.models import ProposalStatus, ProposalType as ProposalTypeEnum
from backend.app.services import ProposalService
from backend.app.services.politician_profile_service import PoliticianProfileService
from scripts.prepare_demo import DemoSafetyError
from scripts.unified_demo import assert_settings_are_unified


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = (
    REPOSITORY_ROOT / "data" / "fixtures" / "reference_profiles" / "giorgia_meloni_v1.json"
)
SOURCE_KEY = "reference-profile"
SOURCE_NAME = "VeraPolitica reference profile fixture"
PROTECTED_ASSESSMENT_TITLE_PREFIX = "Dare seguito al processo virtuoso di autonomia"
NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)


def _normalize(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", folded.casefold()).strip()


def _strip_tracking(url: str) -> str:
    raw = url.strip()
    if raw.startswith("youtube.com/"):
        raw = f"https://www.{raw}"
    elif raw.startswith("www."):
        raw = f"https://{raw}"
    parts = urlsplit(raw)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.casefold().startswith("utm")
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _tokens(value: str) -> set[str]:
    return {token for token in _normalize(value).split() if len(token) > 2}


def _match_existing(pledge: dict[str, Any], existing: list[Proposal]) -> Proposal | None:
    phrases = [_normalize(item) for item in pledge.get("match_phrases") or []]
    title_tokens = _tokens(pledge["title"])
    statement_tokens = _tokens(pledge.get("exact_statement") or "")
    best: tuple[float, Proposal] | None = None
    for proposal in existing:
        haystack = _normalize(f"{proposal.canonical_title} {proposal.exact_statement or ''}")
        if any(phrase and phrase in haystack for phrase in phrases):
            return proposal
        other = _tokens(proposal.canonical_title) | _tokens(proposal.exact_statement or "")
        overlap = title_tokens & other
        if not title_tokens or not other:
            continue
        score = len(overlap) / len(title_tokens | other)
        if statement_tokens:
            score = max(score, len(statement_tokens & other) / len(statement_tokens | other))
        if score >= 0.55 and (best is None or score > best[0]):
            best = (score, proposal)
    return best[1] if best else None


def _source_payloads(items: list[dict[str, Any]]) -> tuple[ProfileSourceInput, ...]:
    payload = []
    for item in items:
        url = item.get("url")
        payload.append(
            ProfileSourceInput(
                title=item.get("title"),
                name=item["name"],
                url=_strip_tracking(url) if url else None,
                kind=ProfileSourceKind(item["kind"]),
                excerpt=item.get("excerpt"),
            )
        )
    return tuple(payload)


def _load_fixture(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "requires editorial verification" not in str(data.get("disclaimer", "")).casefold():
        raise DemoSafetyError("fixture must declare that it requires editorial verification")
    return data


def _find_politician(session: Session, spec: dict[str, Any]) -> Politician:
    birth = date.fromisoformat(spec["birth_date"]) if spec.get("birth_date") else None
    query = select(Politician).where(
        Politician.canonical_given_name == spec["given_name"],
        Politician.canonical_family_name == spec["family_name"],
    )
    if birth is not None:
        query = query.where(Politician.birth_date == birth)
    rows = list(session.scalars(query))
    if len(rows) != 1:
        raise DemoSafetyError(
            f"expected one published politician matching {spec['given_name']} {spec['family_name']}"
        )
    politician = rows[0]
    if politician.current_version_id is None:
        raise DemoSafetyError("politician has no published version")
    return politician


def _existing_pledges(session: Session, politician_id: int) -> list[Proposal]:
    return list(
        session.scalars(
            select(Proposal)
            .join(ProposalActor, ProposalActor.proposal_id == Proposal.id)
            .where(
                ProposalActor.politician_id == politician_id,
                ProposalActor.role == ProposalActorRole.COMMITMENT_OWNER,
                Proposal.proposal_type == ProposalType.EXPLICIT_PROMISE,
                Proposal.published_at.is_not(None),
            )
            .distinct()
        )
    )


def _ensure_document(
    session: Session, fixture: dict[str, Any], *, apply: bool
) -> tuple[int | None, int | None]:
    source = session.scalar(select(Source).where(Source.key == SOURCE_KEY))
    if source is None:
        if not apply:
            return None, None
        source = Source(key=SOURCE_KEY, name=SOURCE_NAME, base_url="https://www.senato.it")
        session.add(source)
        session.flush()
    marker = hashlib.sha256(fixture["fixture_id"].encode()).hexdigest()
    text = "\n".join(
        f"{item['title']}\n{item['exact_statement']}" for item in fixture["pledges"]
    )
    document = session.scalar(
        select(RawDocument).where(RawDocument.storage_key == f"reference-profiles/{fixture['fixture_id']}.txt")
    )
    if document is None:
        if not apply:
            return source.id, None
        document = RawDocument(
            source_id=source.id,
            retrieved_at=NOW,
            source_url=f"verapolitica:fixture:{fixture['fixture_id']}",
            content_type="text/plain",
            storage_key=f"reference-profiles/{fixture['fixture_id']}.txt",
            raw_sha256=marker,
            normalized_sha256=marker,
            structured_records=[],
            normalized_text=text,
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="reference_profile_v1",
            parser_version="reference_profile_v1",
        )
        session.add(document)
        session.flush()
    return source.id, document.id


def _actor(session: Session, politician: Politician) -> ProposalActorObservation:
    identifier = session.scalar(
        select(PoliticianSourceIdentifier).where(
            PoliticianSourceIdentifier.politician_id == politician.id
        )
    )
    if identifier is None:
        raise DemoSafetyError("politician has no source identifier")
    authority = session.get(Source, identifier.source_id)
    if authority is None:
        raise DemoSafetyError("politician source identifier is missing its authority")
    return ProposalActorObservation(
        actor_type=ObservedActorType.POLITICIAN,
        role=ActorRole.COMMITMENT_OWNER,
        display_name=f"{politician.canonical_given_name} {politician.canonical_family_name}",
        authority_key=authority.key,
        source_identifier=identifier.value,
        source_field="reference-profile:politician",
    )


def prepare_reference_profile(
    *,
    fixture_path: Path = DEFAULT_FIXTURE,
    session_factory: sessionmaker[Session] | None = None,
    settings: Settings | None = None,
    dry_run: bool = True,
    allow_non_unified: bool = False,
) -> dict[str, Any]:
    if configured_environment() is AppEnvironment.PRODUCTION:
        raise DemoSafetyError("prepare_reference_profile refuses VERAPOLITICA_ENV=production")
    fixture = _load_fixture(fixture_path)
    apply = not dry_run
    runtime = settings
    if session_factory is None:
        runtime = runtime or get_settings()
        if apply and not allow_non_unified:
            assert_settings_are_unified(
                runtime.database_url,
                runtime.raw_storage_path,
                REPOSITORY_ROOT,
            )
        engine = create_db_engine(runtime.database_url)
        if apply and runtime.database_url.startswith("sqlite"):
            prepare_sqlite_schema(engine)
        session_factory = create_session_factory(engine)

    report: dict[str, Any] = {
        "fixture_id": fixture["fixture_id"],
        "disclaimer": fixture["disclaimer"],
        "dry_run": dry_run,
        "politician_id": None,
        "matched": [],
        "created": [],
        "skipped": [],
        "left_pending": [],
        "left_unpublished": [],
        "assessment_drafts_created": [],
        "protected": [],
        "reconciliation": [],
    }
    service = PoliticianProfileService(session_factory)
    with session_factory() as session:
        politician = _find_politician(session, fixture["politician"])
        politician_id = politician.id
        report["politician_id"] = politician_id
        existing = _existing_pledges(session, politician_id)
        autonomia = [
            row
            for row in existing
            if row.canonical_title.startswith(PROTECTED_ASSESSMENT_TITLE_PREFIX)
        ]
        if autonomia:
            published = session.scalar(
                select(PledgeAssessment).where(PledgeAssessment.proposal_id == autonomia[0].id)
            )
            report["protected"].append(
                {
                    "proposal_id": autonomia[0].id,
                    "title": autonomia[0].canonical_title,
                    "assessment_id": published.id if published else None,
                    "verdict": published.verdict.value if published else None,
                    "action": "untouched",
                }
            )

    actions: list[tuple[str, Any]] = [("biography", fixture["biography"])]
    actions.extend(("career", item) for item in fixture.get("career_entries", []))
    actions.extend(("position", item) for item in fixture.get("positions", []))
    actions.extend(("proceeding", item) for item in fixture.get("proceedings", []))

    for kind, item in actions:
        identity = item["identity_key"]
        if dry_run:
            report["left_pending"].append({"kind": kind, "identity_key": identity})
            continue
        if kind == "biography":
            content_id, disposition = service.upsert_biography(
                politician_id,
                BiographyDraftInput(
                    identity_key=identity,
                    body=item["body"],
                    sources=_source_payloads(item.get("sources") or []),
                    created_by=fixture["created_by"],
                ),
            )
        elif kind == "career":
            content_id, disposition = service.upsert_career_entry(
                politician_id,
                CareerEntryDraftInput(
                    identity_key=identity,
                    start_date=date.fromisoformat(item["start_date"]),
                    end_date=date.fromisoformat(item["end_date"]) if item.get("end_date") else None,
                    start_precision=item.get("start_precision") or "year",
                    end_precision=item.get("end_precision"),
                    is_current=bool(item.get("is_current")),
                    role=item["role"],
                    institution=item["institution"],
                    organization=item.get("organization"),
                    party_or_group=item.get("party_or_group"),
                    sources=_source_payloads(item.get("sources") or []),
                    created_by=fixture["created_by"],
                ),
            )
        elif kind == "position":
            content_id, disposition = service.upsert_position(
                politician_id,
                PositionDraftInput(
                    identity_key=identity,
                    topic=item["topic"],
                    position_statement=item["position_statement"],
                    verifiable_statement=item["verifiable_statement"],
                    statement_date=(
                        date.fromisoformat(item["statement_date"])
                        if item.get("statement_date")
                        else None
                    ),
                    statement_precision=item.get("statement_precision"),
                    sources=_source_payloads(item.get("sources") or []),
                    created_by=fixture["created_by"],
                ),
            )
        else:
            content_id, disposition = service.upsert_proceeding(
                politician_id,
                ProceedingDraftInput(
                    identity_key=identity,
                    title=item["title"],
                    proceeding_types=tuple(item["proceeding_types"]),
                    event_date=(
                        date.fromisoformat(item["event_date"]) if item.get("event_date") else None
                    ),
                    event_precision=item.get("event_precision"),
                    outcome=item.get("outcome"),
                    outcome_date=(
                        date.fromisoformat(item["outcome_date"]) if item.get("outcome_date") else None
                    ),
                    summary=item["summary"],
                    outcome_summary=item.get("outcome_summary"),
                    sources=_source_payloads(item.get("sources") or []),
                    created_by=fixture["created_by"],
                ),
            )
        bucket = "created" if disposition == "created" else "skipped"
        report[bucket].append(
            {"kind": kind, "identity_key": identity, "id": content_id, "status": "pending"}
        )
        if disposition == "created":
            report["left_pending"].append({"kind": kind, "identity_key": identity, "id": content_id})
            report["left_unpublished"].append({"kind": kind, "identity_key": identity})

    with session_factory() as session:
        politician = _find_politician(session, fixture["politician"])
        existing = _existing_pledges(session, politician.id)
        actor = None if dry_run else _actor(session, politician)
        document_id = None
        if not dry_run:
            _ensure_document(session, fixture, apply=True)
            session.commit()
            document_id = session.scalar(
                select(RawDocument.id).where(
                    RawDocument.storage_key == f"reference-profiles/{fixture['fixture_id']}.txt"
                )
            )
        proposals = ProposalService(session_factory)
        for pledge in fixture["pledges"]:
            match = _match_existing(pledge, existing)
            current_verdict = None
            if match is not None:
                assessment = session.scalar(
                    select(PledgeAssessment)
                    .where(PledgeAssessment.proposal_id == match.id)
                    .order_by(PledgeAssessment.created_at.desc(), PledgeAssessment.id.desc())
                )
                current_verdict = assessment.verdict.value if assessment else "not_yet_rated"
            row = {
                "pdf_number": pledge["number"],
                "pdf_title": pledge["title"],
                "existing_proposal_id": match.id if match else None,
                "existing_title": match.canonical_title if match else None,
                "match": "near_duplicate" if match else "missing",
                "current_published_verdict": current_verdict,
                "pdf_implied_verdict": pledge.get("suggested_verdict"),
                "action": "matched_skip_duplicate" if match else "create_proposal_draft",
            }
            if match is not None:
                report["matched"].append(row)
                report["reconciliation"].append(row)
                continue
            report["reconciliation"].append(row)
            if dry_run:
                report["left_pending"].append(
                    {"kind": "pledge", "identity_key": pledge["identity_key"]}
                )
                report["left_unpublished"].append(
                    {"kind": "pledge", "identity_key": pledge["identity_key"]}
                )
                continue
            url = _strip_tracking(pledge["declaration_url"])
            identifier = f"reference-profile:{fixture['fixture_id']}:pledge:{pledge['identity_key']}"
            observation = ProposalObservation(
                source_key=SOURCE_KEY,
                raw_document_id=document_id or 0,
                proposal_identifier=identifier,
                title=pledge["title"],
                exact_statement=pledge["exact_statement"],
                proposal_type=ProposalTypeEnum.EXPLICIT_PROMISE,
                introduced_at=date.fromisoformat(pledge["introduced_at"]),
                source_status_label=pledge.get("origin_label") or "annunciata",
                normalized_status=ProposalStatus.ANNOUNCED,
                official_url=url,
                source_field="reference-profile:promise",
                observed_at=NOW,
                actors=(actor,),
                evidence=tuple(
                    ProposalEvidenceObservation(
                        field_path=path,
                        source_url=url,
                        source_field=field,
                        source_value=value,
                    )
                    for path, field, value in (
                        ("title", "reference-profile:titolo", pledge["title"]),
                        ("proposal_type", "reference-profile:tipo", "explicit_promise"),
                        ("current_status", "reference-profile:stato", "announced"),
                        ("introduced_at", "reference-profile:data", pledge["introduced_at"]),
                        ("exact_statement", "reference-profile:testo", pledge["exact_statement"]),
                    )
                ),
                metadata={
                    "fixture": fixture["fixture_id"],
                    "disclaimer": fixture["disclaimer"],
                    "suggested_verdict": pledge.get("suggested_verdict"),
                    "assessment_note": pledge.get("assessment_note"),
                },
            )
            result = proposals.sync((observation,))
            detail = result.details[0]
            created = detail.disposition.value == "draft_created"
            report["created" if created else "skipped"].append(
                {
                    "kind": "pledge",
                    "identity_key": pledge["identity_key"],
                    "proposal_id": detail.proposal_id,
                    "draft_id": detail.draft_id,
                    "status": "pending",
                }
            )
            report["left_pending"].append(
                {
                    "kind": "pledge",
                    "identity_key": pledge["identity_key"],
                    "proposal_id": detail.proposal_id,
                    "draft_id": detail.draft_id,
                }
            )
            report["left_unpublished"].append(
                {"kind": "pledge", "identity_key": pledge["identity_key"]}
            )
            row["action"] = "proposal_draft_created" if created else "already_observed"
            row["proposal_id"] = detail.proposal_id
            row["draft_id"] = detail.draft_id

    report["notes"] = [
        "No records were auto-published.",
        "No pledge assessment drafts were created: the fixture explanations are not verbatim official excerpts stored in RawDocument.",
        "broken still requires two distinct reviewers after a published pledge and a proposed assessment exist.",
        "The published autonomia assessment is not modified.",
    ]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare a reference politician profile as drafts")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    args = parser.parse_args(argv)
    if args.apply and args.dry_run:
        raise SystemExit("choose either --dry-run or --apply")
    dry_run = not args.apply
    report = prepare_reference_profile(fixture_path=args.fixture, dry_run=dry_run)
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
