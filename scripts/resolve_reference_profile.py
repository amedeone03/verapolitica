"""Resolve Meloni PdC date conflict and report proceeding source gaps.

Uses PoliticianProfileService only. Never invents URLs, never publishes
blocked proceedings, never touches pledges or assessments.

  python -m scripts.resolve_reference_profile giorgia-meloni --dry-run
  python -m scripts.resolve_reference_profile giorgia-meloni --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import AppEnvironment, configured_environment
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.models import PoliticianVersionCitation, RawDocument
from backend.app.models.politician_profile import (
    PoliticianBiography,
    PoliticianCareerEntry,
    PoliticianPosition,
    PoliticianProceeding,
    PoliticianProfileSource,
    ProfileContentKind,
    ProfileContentStatus,
)
from backend.app.schemas.politician_profile import BiographyDraftInput, SourceCompleteness
from backend.app.services.politician_profile_service import PoliticianProfileService
from backend.app.services.reference_profile_audit import (
    DEFAULT_FIXTURE,
    audit_from_factory,
    resolve_politician,
)
from scripts.approve_reference_profile import select_assessments_for
from scripts.audit_reference_profile import resolve_database_url
from scripts.prepare_demo import DemoSafetyError
from scripts.prepare_reference_profile import PROTECTED_ASSESSMENT_TITLE_PREFIX
from scripts.unified_demo import UnifiedDemoPaths, assert_settings_are_unified


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REVIEWER = "reference-profile-editor"
PRECISE_PDF_DATE = "dal 22 ottobre 2022"
NEUTRAL_MANDATE = "dall’ottobre 2022"
PDC_IDENTITY = "presidente-consiglio-2022"
BIO_IDENTITY = "primary"
BIOGRAPHY_NOTE = (
    "Neutralized PdC day date to month precision. Collected Governo/Gazzetta "
    "appointment 2022-10-21 remains the public mandate; PDF 22 October is not "
    "used as a day-precise public claim."
)
PDC_REJECT_NOTE = (
    "Duplicative of the collected PdC mandate 2022-10-21 (Gazzetta appointment "
    "https://www.gazzettaufficiale.it/eli/id/2022/10/25/22A06174/sg). "
    "PDF/curriculum 2022-10-22 is a one-day discrepancy; collected mandate "
    "remains authoritative."
)


def _load_fixture(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _revised_body(body: str) -> str:
    if PRECISE_PDF_DATE in body:
        return body.replace(PRECISE_PDF_DATE, NEUTRAL_MANDATE)
    return body


def _body_is_consistent(body: str) -> bool:
    return PRECISE_PDF_DATE not in body and NEUTRAL_MANDATE in body


def _outlet_urls(session: Session) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for row in session.scalars(
        select(PoliticianProfileSource).where(PoliticianProfileSource.url.is_not(None))
    ):
        found.setdefault(row.name, []).append(row.url)
    for row in session.scalars(
        select(PoliticianVersionCitation).where(
            PoliticianVersionCitation.source_url.is_not(None)
        )
    ):
        found.setdefault(row.source_name, []).append(row.source_url)
    for row in session.scalars(
        select(RawDocument).where(RawDocument.source_url.is_not(None))
    ):
        found.setdefault(row.source_url, []).append(row.source_url)
    return found


def _proceeding_source_audit(
    session: Session, fixture: dict[str, Any]
) -> list[dict[str, Any]]:
    outlet_urls = _outlet_urls(session)
    reports: list[dict[str, Any]] = []
    for item in fixture.get("proceedings") or []:
        row = session.scalar(
            select(PoliticianProceeding).where(
                PoliticianProceeding.identity_key == item["identity_key"],
                PoliticianProceeding.status == ProfileContentStatus.PENDING,
            )
        )
        stored = []
        if row is not None:
            stored = PoliticianProfileService._sources(
                session, ProfileContentKind.PROCEEDING, row.id
            )
        stored_by_name = {source.name: source for source in stored}
        sources = []
        recoverable = False
        for declared in item.get("sources") or []:
            name = declared["name"]
            fixture_url = declared.get("url")
            current = stored_by_name.get(name)
            current_url = current.url if current is not None else None
            same_outlet = [
                url
                for url in outlet_urls.get(name, [])
                if url and url != current_url
            ]
            item_recoverable = bool(fixture_url) or bool(current_url)
            recoverable = recoverable or item_recoverable
            sources.append(
                {
                    "name": name,
                    "kind": declared.get("kind"),
                    "fixture_url": fixture_url,
                    "current_url": current_url,
                    "same_outlet_unrelated_urls": sorted(set(same_outlet)),
                    "recoverable": item_recoverable,
                    "reason": (
                        "exact URL already present"
                        if item_recoverable
                        else "name-only source; do not invent or borrow unrelated outlet URLs"
                    ),
                }
            )
        wording_ok = True
        issues = []
        summary = (item.get("summary") or "") + " " + (item.get("outcome_summary") or "")
        types = set(item.get("proceeding_types") or [])
        if item["identity_key"] == "caso-almasri-2025":
            if "judicial_proceeding" not in types or item.get("outcome") != "archived":
                wording_ok = False
                issues.append("Almasri must remain a personal judicial proceeding with archived outcome")
        if item["identity_key"] == "naufragio-cutro-2023":
            if "political_controversy" not in types or "judicial_proceeding" in types:
                wording_ok = False
                issues.append("Cutro must remain a political controversy, not a personal criminal proceeding")
            if "procedimento penale personale" not in summary.casefold():
                wording_ok = False
                issues.append("Cutro wording no longer states it is not a personal criminal proceeding")
        if item["identity_key"] == "accordo-italia-albania-2023":
            if "judicial_proceeding" in types:
                wording_ok = False
                issues.append("Italia–Albania must not be typed as a personal judicial proceeding")
        if item["identity_key"] == "gioventu-nazionale-2024":
            if "non comportano automaticamente responsabilità personali" not in summary:
                wording_ok = False
                issues.append("Gioventù Nazionale must not attribute member actions automatically to Meloni")
        reports.append(
            {
                "identity_key": item["identity_key"],
                "title": item["title"],
                "content_id": row.id if row is not None else None,
                "status": row.status.value if row is not None else None,
                "sources": sources,
                "wording_ok": wording_ok,
                "wording_issues": issues,
                "ready_if_urls_attached": wording_ok and recoverable,
            }
        )
    return reports


def _counts(session: Session, politician_id: int) -> dict[str, dict[str, int]]:
    from sqlalchemy import func

    result: dict[str, dict[str, int]] = {}
    for name, model in (
        ("biography", PoliticianBiography),
        ("career", PoliticianCareerEntry),
        ("positions", PoliticianPosition),
        ("proceedings", PoliticianProceeding),
    ):
        pending = session.scalar(
            select(func.count())
            .select_from(model)
            .where(
                model.politician_id == politician_id,
                model.status == ProfileContentStatus.PENDING,
            )
        )
        published = session.scalar(
            select(func.count())
            .select_from(model)
            .where(
                model.politician_id == politician_id,
                model.status == ProfileContentStatus.PUBLISHED,
            )
        )
        rejected = session.scalar(
            select(func.count())
            .select_from(model)
            .where(
                model.politician_id == politician_id,
                model.status == ProfileContentStatus.REJECTED,
            )
        )
        superseded = session.scalar(
            select(func.count())
            .select_from(model)
            .where(
                model.politician_id == politician_id,
                model.status == ProfileContentStatus.SUPERSEDED,
            )
        )
        result[name] = {
            "pending": int(pending or 0),
            "published": int(published or 0),
            "rejected": int(rejected or 0),
            "superseded": int(superseded or 0),
        }
    return result


def resolve_reference_profile(
    slug: str,
    *,
    session_factory: sessionmaker[Session] | None = None,
    fixture_path: Path = DEFAULT_FIXTURE,
    dry_run: bool = True,
    allow_non_unified: bool = False,
    database_url: str | None = None,
    reviewer: str = REVIEWER,
) -> dict[str, Any]:
    if configured_environment() is AppEnvironment.PRODUCTION:
        raise DemoSafetyError("resolve_reference_profile refuses VERAPOLITICA_ENV=production")
    engine = None
    if session_factory is None:

        class _Args:
            unified_demo = True

        _Args.database_url = database_url
        url = resolve_database_url(_Args())
        if not allow_non_unified:
            paths = UnifiedDemoPaths.for_workspace(REPOSITORY_ROOT)
            assert_settings_are_unified(url, paths.raw_storage, REPOSITORY_ROOT)
        engine = create_db_engine(url)
        session_factory = create_session_factory(engine)

    fixture = _load_fixture(fixture_path)
    report: dict[str, Any] = {
        "slug": slug,
        "dry_run": dry_run,
        "politician_id": None,
        "politician_name": None,
        "mandate_start": None,
        "mandate_source_url": None,
        "biography": {"action": "none", "reason": ""},
        "pdc_career": {"action": "none", "reason": ""},
        "proceedings": [],
        "approved_proceedings": [],
        "pledges_untouched": True,
        "assessments_untouched": [],
        "notes": [
            "Does not invent proceeding URLs.",
            "Does not approve MISSING_SOURCE_URL items.",
            "Does not touch pledge drafts or assessments.",
        ],
    }
    try:
        service = PoliticianProfileService(session_factory)
        with session_factory() as session:
            politician = resolve_politician(session, slug)
            report["politician_id"] = politician.id
            report["politician_name"] = (
                f"{politician.canonical_given_name} {politician.canonical_family_name}"
            )
            version = politician.current_version
            if version is not None:
                mandates = (version.profile_data or {}).get("mandates") or []
                if mandates:
                    report["mandate_start"] = mandates[0].get("start_date")
                citation = session.scalar(
                    select(PoliticianVersionCitation).where(
                        PoliticianVersionCitation.politician_version_id == version.id,
                        PoliticianVersionCitation.field_path == "mandates[0].start_date",
                    )
                )
                if citation is not None:
                    report["mandate_source_url"] = citation.source_url
            published_bio = session.scalar(
                select(PoliticianBiography).where(
                    PoliticianBiography.politician_id == politician.id,
                    PoliticianBiography.identity_key == BIO_IDENTITY,
                    PoliticianBiography.status == ProfileContentStatus.PUBLISHED,
                )
            )
            pending_bio = session.scalar(
                select(PoliticianBiography).where(
                    PoliticianBiography.politician_id == politician.id,
                    PoliticianBiography.identity_key == BIO_IDENTITY,
                    PoliticianBiography.status == ProfileContentStatus.PENDING,
                )
            )
            pdc = session.scalar(
                select(PoliticianCareerEntry).where(
                    PoliticianCareerEntry.politician_id == politician.id,
                    PoliticianCareerEntry.identity_key == PDC_IDENTITY,
                )
            )
            report["proceedings"] = _proceeding_source_audit(session, fixture)
            bio_source_row = published_bio or pending_bio
            bio_sources = (
                PoliticianProfileService.source_inputs(
                    session, ProfileContentKind.BIOGRAPHY, bio_source_row.id
                )
                if bio_source_row is not None
                else ()
            )
            pending_bio_id = pending_bio.id if pending_bio is not None else None
            pending_bio_body = pending_bio.body if pending_bio is not None else None
            published_bio_id = published_bio.id if published_bio is not None else None
            published_bio_body = published_bio.body if published_bio is not None else None
            pdc_id = pdc.id if pdc is not None else None
            pdc_status = pdc.status if pdc is not None else None
            pdc_start = pdc.start_date.isoformat() if pdc is not None else None
            current_body = pending_bio_body or published_bio_body
            revised = _revised_body(current_body) if current_body else None

        if current_body is None:
            report["biography"] = {
                "action": "skipped",
                "reason": "no biography row",
            }
        elif _body_is_consistent(current_body) and pending_bio_id is None:
            report["biography"] = {
                "action": "already_consistent",
                "reason": "published biography already uses month precision",
                "id": published_bio_id,
            }
        elif dry_run:
            report["biography"] = {
                "action": "would_revise",
                "reason": BIOGRAPHY_NOTE,
                "from": current_body,
                "to": revised,
            }
        else:
            if pending_bio_id is not None and not _body_is_consistent(pending_bio_body or ""):
                service.reject(
                    ProfileContentKind.BIOGRAPHY,
                    pending_bio_id,
                    reviewer=reviewer,
                    note=BIOGRAPHY_NOTE,
                )
                pending_bio_id = None
            if pending_bio_id is None:
                content_id, _disposition = service.upsert_biography(
                    report["politician_id"],
                    BiographyDraftInput(
                        identity_key=BIO_IDENTITY,
                        body=revised or current_body,
                        sources=bio_sources,
                        created_by=reviewer,
                    ),
                )
                pending_bio_id = content_id
            detail = service.approve(
                ProfileContentKind.BIOGRAPHY,
                pending_bio_id,
                reviewer=reviewer,
                note=BIOGRAPHY_NOTE,
            )
            report["biography"] = {
                "action": "revised_and_published",
                "reason": BIOGRAPHY_NOTE,
                "id": detail.id,
                "status": detail.status.value,
            }

        if pdc_id is None:
            report["pdc_career"] = {
                "action": "absent",
                "reason": "no duplicative PdC career row",
            }
        elif pdc_status is ProfileContentStatus.REJECTED:
            report["pdc_career"] = {
                "action": "already_rejected",
                "id": pdc_id,
                "start_date": pdc_start,
            }
        elif pdc_status is not ProfileContentStatus.PENDING:
            report["pdc_career"] = {
                "action": "skipped",
                "reason": f"status is {pdc_status.value if pdc_status else None}",
                "id": pdc_id,
            }
        elif dry_run:
            report["pdc_career"] = {
                "action": "would_reject",
                "reason": PDC_REJECT_NOTE,
                "id": pdc_id,
                "start_date": pdc_start,
            }
        else:
            detail = service.reject(
                ProfileContentKind.CAREER_ENTRY,
                pdc_id,
                reviewer=reviewer,
                note=PDC_REJECT_NOTE,
            )
            report["pdc_career"] = {
                "action": "rejected",
                "reason": PDC_REJECT_NOTE,
                "id": detail.id,
                "status": detail.status.value,
            }

        audit = audit_from_factory(session_factory, slug, fixture_path=fixture_path)
        report["audit_proceedings"] = [
            {
                "identity_key": item.identity_key,
                "source_completeness": item.source_completeness,
                "blocker": item.blocker,
                "publication_status": item.publication_status,
            }
            for item in audit.profile_items
            if item.content_type == ProfileContentKind.PROCEEDING.value
        ]
        ready_proceedings = [
            item
            for item in audit.profile_items
            if item.content_type == ProfileContentKind.PROCEEDING.value
            and item.source_completeness
            == SourceCompleteness.READY_FOR_EDITORIAL_REVIEW.value
            and item.publication_status == ProfileContentStatus.PENDING.value
        ]
        if dry_run:
            report["approved_proceedings"] = [
                {"action": "would_approve", "identity_key": item.identity_key, "id": item.id}
                for item in ready_proceedings
            ]
        else:
            for item in ready_proceedings:
                detail = service.approve(
                    ProfileContentKind.PROCEEDING,
                    item.id,
                    reviewer=reviewer,
                    note="Approved only after source-completeness READY_FOR_EDITORIAL_REVIEW.",
                )
                report["approved_proceedings"].append(
                    {
                        "action": "approved",
                        "identity_key": item.identity_key,
                        "id": detail.id,
                        "status": detail.status.value,
                    }
                )

        with session_factory() as session:
            report["counts"] = _counts(session, report["politician_id"])
            assessments = list(
                session.scalars(select_assessments_for(session, report["politician_id"]))
            )
            report["assessments_untouched"] = [
                {
                    "id": item.id,
                    "proposal_id": item.proposal_id,
                    "verdict": item.verdict.value,
                    "protected": item.proposal.canonical_title.startswith(
                        PROTECTED_ASSESSMENT_TITLE_PREFIX
                    )
                    if item.proposal is not None
                    else False,
                }
                for item in assessments
            ]
        return report
    finally:
        if engine is not None:
            engine.dispose()


def format_resolve_text(report: dict[str, Any]) -> str:
    mode = "DRY-RUN" if report["dry_run"] else "APPLY"
    lines = [
        f"{mode}  {report['politician_name']} (id {report['politician_id']})",
        f"mandate_start: {report['mandate_start']}",
        f"mandate_source_url: {report['mandate_source_url']}",
        "",
        f"biography: {report['biography'].get('action')}  {report['biography'].get('reason', '')}",
        f"pdc_career: {report['pdc_career'].get('action')}  id={report['pdc_career'].get('id')}",
        f"approved_proceedings: {len(report['approved_proceedings'])}",
        "",
        "PROCEEDINGS",
    ]
    for item in report["proceedings"]:
        lines.append(f"  {item['identity_key']}  status={item['status']} wording_ok={item['wording_ok']}")
        for source in item["sources"]:
            lines.append(
                f"    {source['name']}  recoverable={source['recoverable']}  {source['reason']}"
            )
        for issue in item["wording_issues"]:
            lines.append(f"    wording: {issue}")
    lines.append("")
    for item in report.get("audit_proceedings") or []:
        lines.append(
            f"  audit {item['identity_key']}: {item['source_completeness']} ({item['blocker']})"
        )
    counts = report.get("counts") or {}
    if counts:
        lines.append("")
        lines.append("COUNTS")
        for name, values in counts.items():
            lines.append(
                f"  {name}: {values['published']} published / {values['pending']} pending "
                f"/ {values['rejected']} rejected / {values['superseded']} superseded"
            )
    lines.append("")
    lines.append(f"pledges_untouched: {report['pledges_untouched']}")
    for item in report["assessments_untouched"]:
        lines.append(
            f"assessment {item['id']} proposal {item['proposal_id']} "
            f"{item['verdict']} protected={item['protected']}"
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resolve PdC date conflict and audit proceeding sources in the unified demo."
    )
    parser.add_argument("slug", help="politician slug, e.g. giorgia-meloni")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--database-url")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.apply and args.dry_run:
        print("choose either --dry-run or --apply", file=sys.stderr)
        return 2
    dry_run = not args.apply
    try:
        report = resolve_reference_profile(
            args.slug,
            fixture_path=args.fixture,
            dry_run=dry_run,
            allow_non_unified=False,
            database_url=args.database_url,
        )
    except (DemoSafetyError, LookupError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(format_resolve_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
