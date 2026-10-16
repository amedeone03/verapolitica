"""Add editorially reviewed politician profile narrative tables.

Revision ID: f3c9a7d14e52
Revises: e2b8f6c03d41
Create Date: 2026-10-16

Generic biography, career, position and proceeding records. Public APIs expose
only published rows; drafts stay pending until editorial approval.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3c9a7d14e52"
down_revision: Union[str, Sequence[str], None] = "e2b8f6c03d41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


STATUS = sa.Enum(
    "pending",
    "published",
    "rejected",
    "superseded",
    name="profilecontentstatus",
    native_enum=False,
    length=32,
)
PRECISION = sa.Enum(
    "year",
    "month",
    "day",
    name="dateprecision",
    native_enum=False,
    length=16,
)
SOURCE_KIND = sa.Enum(
    "official",
    "institutional",
    "news",
    "party_politician",
    "fact_check",
    "other",
    name="profilesourcekind",
    native_enum=False,
    length=32,
)
CONTENT_KIND = sa.Enum(
    "biography",
    "career_entry",
    "position",
    "proceeding",
    name="profilecontentkind",
    native_enum=False,
    length=32,
)
OUTCOME = sa.Enum(
    "archived",
    "ongoing",
    "dismissed",
    "unknown",
    name="proceedingoutcome",
    native_enum=False,
    length=32,
)


def _content_columns():
    return (
        sa.Column("politician_id", sa.Integer(), nullable=False),
        sa.Column("politician_version_id", sa.Integer(), nullable=True),
        sa.Column("identity_key", sa.String(length=120), nullable=False),
        sa.Column("status", STATUS, nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("reviewed_by", sa.String(length=200), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["politician_id"], ["politicians.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["politician_version_id"], ["politician_versions.id"], ondelete="RESTRICT"
        ),
    )


def upgrade() -> None:
    op.create_table(
        "politician_biographies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        *_content_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_politician_biographies_identity",
        "politician_biographies",
        ["politician_id", "identity_key", "status"],
    )
    op.create_index(
        op.f("ix_politician_biographies_politician_id"),
        "politician_biographies",
        ["politician_id"],
    )
    op.create_index(
        op.f("ix_politician_biographies_politician_version_id"),
        "politician_biographies",
        ["politician_version_id"],
    )
    op.create_index(
        op.f("ix_politician_biographies_identity_key"),
        "politician_biographies",
        ["identity_key"],
    )
    op.create_index(
        op.f("ix_politician_biographies_status"),
        "politician_biographies",
        ["status"],
    )
    op.create_index(
        op.f("ix_politician_biographies_published_at"),
        "politician_biographies",
        ["published_at"],
    )

    op.create_table(
        "politician_career_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("start_precision", PRECISION, nullable=False),
        sa.Column("end_precision", PRECISION, nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("role", sa.String(length=500), nullable=False),
        sa.Column("institution", sa.String(length=500), nullable=False),
        sa.Column("organization", sa.String(length=500), nullable=True),
        sa.Column("party_or_group", sa.String(length=500), nullable=True),
        *_content_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_politician_career_entries_identity",
        "politician_career_entries",
        ["politician_id", "identity_key", "status"],
    )
    op.create_index(
        op.f("ix_politician_career_entries_politician_id"),
        "politician_career_entries",
        ["politician_id"],
    )
    op.create_index(
        op.f("ix_politician_career_entries_politician_version_id"),
        "politician_career_entries",
        ["politician_version_id"],
    )
    op.create_index(
        op.f("ix_politician_career_entries_identity_key"),
        "politician_career_entries",
        ["identity_key"],
    )
    op.create_index(
        op.f("ix_politician_career_entries_status"),
        "politician_career_entries",
        ["status"],
    )
    op.create_index(
        op.f("ix_politician_career_entries_published_at"),
        "politician_career_entries",
        ["published_at"],
    )
    op.create_index(
        op.f("ix_politician_career_entries_start_date"),
        "politician_career_entries",
        ["start_date"],
    )

    op.create_table(
        "politician_positions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("topic", sa.String(length=200), nullable=False),
        sa.Column("position_statement", sa.Text(), nullable=False),
        sa.Column("verifiable_statement", sa.Text(), nullable=False),
        sa.Column("statement_date", sa.Date(), nullable=True),
        sa.Column("statement_precision", PRECISION, nullable=True),
        *_content_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_politician_positions_identity",
        "politician_positions",
        ["politician_id", "identity_key", "status"],
    )
    op.create_index(
        op.f("ix_politician_positions_politician_id"),
        "politician_positions",
        ["politician_id"],
    )
    op.create_index(
        op.f("ix_politician_positions_politician_version_id"),
        "politician_positions",
        ["politician_version_id"],
    )
    op.create_index(
        op.f("ix_politician_positions_identity_key"),
        "politician_positions",
        ["identity_key"],
    )
    op.create_index(
        op.f("ix_politician_positions_status"),
        "politician_positions",
        ["status"],
    )
    op.create_index(
        op.f("ix_politician_positions_published_at"),
        "politician_positions",
        ["published_at"],
    )

    op.create_table(
        "politician_proceedings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("proceeding_types", sa.JSON(), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("event_precision", PRECISION, nullable=True),
        sa.Column("outcome", OUTCOME, nullable=True),
        sa.Column("outcome_date", sa.Date(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("outcome_summary", sa.Text(), nullable=True),
        *_content_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_politician_proceedings_identity",
        "politician_proceedings",
        ["politician_id", "identity_key", "status"],
    )
    op.create_index(
        op.f("ix_politician_proceedings_politician_id"),
        "politician_proceedings",
        ["politician_id"],
    )
    op.create_index(
        op.f("ix_politician_proceedings_politician_version_id"),
        "politician_proceedings",
        ["politician_version_id"],
    )
    op.create_index(
        op.f("ix_politician_proceedings_identity_key"),
        "politician_proceedings",
        ["identity_key"],
    )
    op.create_index(
        op.f("ix_politician_proceedings_status"),
        "politician_proceedings",
        ["status"],
    )
    op.create_index(
        op.f("ix_politician_proceedings_published_at"),
        "politician_proceedings",
        ["published_at"],
    )

    op.create_table(
        "politician_profile_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("content_kind", CONTENT_KIND, nullable=False),
        sa.Column("content_id", sa.Integer(), nullable=False),
        sa.Column("sort_index", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("kind", SOURCE_KIND, nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("incomplete", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "content_kind",
            "content_id",
            "sort_index",
            name="uq_politician_profile_source_slot",
        ),
    )
    op.create_index(
        "ix_politician_profile_sources_content",
        "politician_profile_sources",
        ["content_kind", "content_id", "sort_index"],
    )
    op.create_index(
        op.f("ix_politician_profile_sources_content_kind"),
        "politician_profile_sources",
        ["content_kind"],
    )
    op.create_index(
        op.f("ix_politician_profile_sources_content_id"),
        "politician_profile_sources",
        ["content_id"],
    )


def downgrade() -> None:
    op.drop_table("politician_profile_sources")
    op.drop_table("politician_proceedings")
    op.drop_table("politician_positions")
    op.drop_table("politician_career_entries")
    op.drop_table("politician_biographies")
