from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from backend.app.db.schema import alembic_config
from backend.app.db.session import create_db_engine, create_session_factory

_SAFE_DB_NAME = re.compile(r"^[a-z][a-z0-9_]{1,62}$")


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
        "voting_guides",
        "glossary_terms",
        "referendums",
        "referendum_source_identifiers",
        "referendum_drafts",
        "referendum_evidence",
        "referendum_reviews",
        "notification_subscriptions",
        "notification_reminder_candidates",
        "pledge_classifications",
        "pledge_assessment_drafts",
        "pledge_assessment_approvals",
        "pledge_assessments",
        "pledge_audit_samples",
        "pledge_audit_codings",
        "pledge_evidence_candidates",
    }
)


def postgres_url() -> str:
    url = os.environ.get("VERAPOLITICA_POSTGRES_TEST_URL", "").strip()
    if not url:
        pytest.skip("VERAPOLITICA_POSTGRES_TEST_URL is not set")
    return url


@contextmanager
def isolated_postgres_database(name: str) -> Iterator[str]:
    """Create an empty PostgreSQL database and drop it when the test ends."""

    if not _SAFE_DB_NAME.fullmatch(name):
        raise ValueError(f"unsafe database name: {name}")
    source = make_url(postgres_url())
    admin = create_engine(
        source.render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )

    def _drop() -> None:
        with admin.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))

    try:
        _drop()
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        yield source.set(database=name).render_as_string(hide_password=False)
    finally:
        try:
            _drop()
        finally:
            admin.dispose()


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
