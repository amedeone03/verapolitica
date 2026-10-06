from __future__ import annotations

from alembic import command
from sqlalchemy import Engine, inspect
from sqlalchemy.orm import Session, sessionmaker

from backend.app.db.schema import alembic_config
from backend.app.db.session import create_db_engine, create_session_factory


EXPECTED_TABLES = frozenset(
    {
        "sources",
        "raw_documents",
        "politicians",
        "politician_source_identifiers",
        "politician_versions",
        "politician_version_citations",
        "profile_drafts",
        "evidence",
        "reviews",
        "identity_resolution_cases",
        "parliamentary_groups",
        "parliamentary_group_source_identifiers",
        "parliamentary_group_memberships",
        "political_parties",
        "political_party_source_identifiers",
        "political_party_affiliations",
        "proposals",
        "proposal_source_identifiers",
        "proposal_actors",
        "proposal_status_events",
        "proposal_drafts",
        "proposal_evidence",
        "proposal_reviews",
        "document_chunks",
        "ai_extraction_runs",
        "ai_extraction_candidates",
        "ai_extraction_candidate_evidence",
        "ai_extraction_evaluation_runs",
        "regions",
        "municipalities",
        "territorial_office_mandates",
        "ingestion_job_runs",
    }
)


def migrate_sqlite(tmp_path) -> tuple[str, Engine, sessionmaker[Session]]:
    url = f"sqlite:///{tmp_path / 'alembic.db'}"
    command.upgrade(alembic_config(url), "head")
    engine = create_db_engine(url)
    return url, engine, create_session_factory(engine)


def constraint_names(engine: Engine, table: str) -> set[str]:
    inspector = inspect(engine)
    names = {item["name"] for item in inspector.get_unique_constraints(table)}
    names.update(
        index["name"] for index in inspector.get_indexes(table) if index.get("unique")
    )
    names.update(item["name"] for item in inspector.get_check_constraints(table))
    pk = inspector.get_pk_constraint(table)
    if pk and pk.get("name"):
        names.add(pk["name"])
    return {name for name in names if name}
