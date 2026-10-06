"""Add citizen search columns and PostgreSQL trigram indexes.

Revision ID: b7c4e2a91f10
Revises: 1864a1eb302a
Create Date: 2026-10-06

pg_trgm is enabled on PostgreSQL so conservative name typos can use
similarity() without ranking above exact/prefix matches. SQLite keeps
btree indexes and LIKE fallback only.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from backend.app.core.text import normalize_search_text


revision: str = "b7c4e2a91f10"
down_revision: Union[str, Sequence[str], None] = "1864a1eb302a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "regions",
        sa.Column("search_primary", sa.String(length=500), server_default="", nullable=False),
    )
    op.add_column(
        "regions",
        sa.Column("search_document", sa.Text(), server_default="", nullable=False),
    )
    op.add_column(
        "municipalities",
        sa.Column("search_primary", sa.String(length=500), server_default="", nullable=False),
    )
    op.add_column(
        "municipalities",
        sa.Column("search_document", sa.Text(), server_default="", nullable=False),
    )
    op.add_column(
        "parliamentary_groups",
        sa.Column("search_primary", sa.String(length=500), server_default="", nullable=False),
    )
    op.add_column(
        "parliamentary_groups",
        sa.Column("search_document", sa.Text(), server_default="", nullable=False),
    )
    op.add_column(
        "political_parties",
        sa.Column("search_primary", sa.String(length=500), server_default="", nullable=False),
    )
    op.add_column(
        "political_parties",
        sa.Column("search_document", sa.Text(), server_default="", nullable=False),
    )
    op.add_column(
        "proposals",
        sa.Column("search_primary", sa.String(length=500), server_default="", nullable=False),
    )
    op.add_column(
        "proposals",
        sa.Column("search_document", sa.Text(), server_default="", nullable=False),
    )
    op.add_column(
        "proposal_actors",
        sa.Column("search_primary", sa.String(length=500), server_default="", nullable=False),
    )
    _backfill()
    op.create_index("ix_regions_search_primary", "regions", ["search_primary"])
    op.create_index("ix_municipalities_search_primary", "municipalities", ["search_primary"])
    op.create_index("ix_municipalities_search_document", "municipalities", ["search_document"])
    op.create_index(
        "ix_parliamentary_groups_search_primary",
        "parliamentary_groups",
        ["search_primary"],
    )
    op.create_index(
        "ix_political_parties_search_primary", "political_parties", ["search_primary"]
    )
    op.create_index("ix_proposals_search_primary", "proposals", ["search_primary"])
    op.create_index(
        "ix_proposal_actors_search_primary", "proposal_actors", ["search_primary"]
    )
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        op.execute(
            sa.text(
                "CREATE INDEX ix_municipalities_search_primary_trgm "
                "ON municipalities USING gin (search_primary gin_trgm_ops)"
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX ix_municipalities_search_document_trgm "
                "ON municipalities USING gin (search_document gin_trgm_ops)"
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX ix_politicians_normalized_name_trgm "
                "ON politicians USING gin (normalized_name gin_trgm_ops)"
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX ix_proposals_search_primary_trgm "
                "ON proposals USING gin (search_primary gin_trgm_ops)"
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX ix_regions_search_primary_trgm "
                "ON regions USING gin (search_primary gin_trgm_ops)"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("DROP INDEX IF EXISTS ix_regions_search_primary_trgm"))
        op.execute(sa.text("DROP INDEX IF EXISTS ix_proposals_search_primary_trgm"))
        op.execute(sa.text("DROP INDEX IF EXISTS ix_politicians_normalized_name_trgm"))
        op.execute(sa.text("DROP INDEX IF EXISTS ix_municipalities_search_document_trgm"))
        op.execute(sa.text("DROP INDEX IF EXISTS ix_municipalities_search_primary_trgm"))
    op.drop_index("ix_proposal_actors_search_primary", table_name="proposal_actors")
    op.drop_index("ix_proposals_search_primary", table_name="proposals")
    op.drop_index("ix_political_parties_search_primary", table_name="political_parties")
    op.drop_index(
        "ix_parliamentary_groups_search_primary", table_name="parliamentary_groups"
    )
    op.drop_index("ix_municipalities_search_document", table_name="municipalities")
    op.drop_index("ix_municipalities_search_primary", table_name="municipalities")
    op.drop_index("ix_regions_search_primary", table_name="regions")
    op.drop_column("proposal_actors", "search_primary")
    op.drop_column("proposals", "search_document")
    op.drop_column("proposals", "search_primary")
    op.drop_column("political_parties", "search_document")
    op.drop_column("political_parties", "search_primary")
    op.drop_column("parliamentary_groups", "search_document")
    op.drop_column("parliamentary_groups", "search_primary")
    op.drop_column("municipalities", "search_document")
    op.drop_column("municipalities", "search_primary")
    op.drop_column("regions", "search_document")
    op.drop_column("regions", "search_primary")


def _backfill() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, canonical_name FROM regions"))
    for row in rows:
        primary = normalize_search_text(row.canonical_name)
        bind.execute(
            sa.text(
                "UPDATE regions SET search_primary = :primary, search_document = :primary WHERE id = :id"
            ),
            {"primary": primary, "id": row.id},
        )
    rows = bind.execute(
        sa.text(
            "SELECT id, canonical_name, province_name, province_abbreviation FROM municipalities"
        )
    )
    for row in rows:
        primary = normalize_search_text(row.canonical_name)
        document = normalize_search_text(
            f"comune {row.canonical_name} {row.province_abbreviation}"
        )
        bind.execute(
            sa.text(
                "UPDATE municipalities SET search_primary = :primary, search_document = :document WHERE id = :id"
            ),
            {"primary": primary, "document": document, "id": row.id},
        )
    rows = bind.execute(
        sa.text(
            "SELECT id, canonical_name, abbreviation, institution, legislature "
            "FROM parliamentary_groups"
        )
    )
    for row in rows:
        primary = normalize_search_text(row.canonical_name)
        document = normalize_search_text(
            f"{row.canonical_name} {row.abbreviation or ''} {row.institution} {row.legislature}"
        )
        bind.execute(
            sa.text(
                "UPDATE parliamentary_groups SET search_primary = :primary, search_document = :document WHERE id = :id"
            ),
            {"primary": primary, "document": document, "id": row.id},
        )
    rows = bind.execute(sa.text("SELECT id, canonical_name, abbreviation FROM political_parties"))
    for row in rows:
        primary = normalize_search_text(row.canonical_name)
        document = normalize_search_text(f"{row.canonical_name} {row.abbreviation or ''}")
        bind.execute(
            sa.text(
                "UPDATE political_parties SET search_primary = :primary, search_document = :document WHERE id = :id"
            ),
            {"primary": primary, "document": document, "id": row.id},
        )
    rows = bind.execute(
        sa.text(
            "SELECT id, canonical_title, summary, exact_statement, proposal_type FROM proposals"
        )
    )
    for row in rows:
        primary = normalize_search_text(row.canonical_title)
        document = normalize_search_text(
            f"{row.canonical_title} {row.summary or ''} {row.exact_statement or ''} {row.proposal_type}"
        )
        bind.execute(
            sa.text(
                "UPDATE proposals SET search_primary = :primary, search_document = :document WHERE id = :id"
            ),
            {"primary": primary, "document": document, "id": row.id},
        )
    rows = bind.execute(sa.text("SELECT id, display_name FROM proposal_actors"))
    for row in rows:
        bind.execute(
            sa.text("UPDATE proposal_actors SET search_primary = :primary WHERE id = :id"),
            {"primary": normalize_search_text(row.display_name), "id": row.id},
        )
