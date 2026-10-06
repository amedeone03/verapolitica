"""Add civic referendum, voting guide, glossary, and reminder tables.

Revision ID: c8d5f3b02a21
Revises: b7c4e2a91f10
Create Date: 2026-10-06

Additive civic-features schema. Search indexes for published referendums
and glossary terms reuse the existing PostgreSQL pg_trgm extension when
present. No previous revision is modified.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8d5f3b02a21"
down_revision: Union[str, Sequence[str], None] = "b7c4e2a91f10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "voting_guides",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column(
            "scope",
            sa.Enum(
                "national",
                "region",
                "municipality",
                name="geographicscopetype",
                native_enum=False,
                length=64,
            ),
            nullable=False,
        ),
        sa.Column("sections", sa.JSON(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voting_guides_source_id", "voting_guides", ["source_id"])
    op.create_index("ix_voting_guides_published_at", "voting_guides", ["published_at"])

    op.create_table(
        "glossary_terms",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=200), nullable=False),
        sa.Column("term", sa.String(length=300), nullable=False),
        sa.Column("short_definition", sa.Text(), nullable=False),
        sa.Column("extended_definition", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("search_primary", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("search_document", sa.Text(), nullable=False, server_default=""),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_glossary_terms_slug", "glossary_terms", ["slug"], unique=True)
    op.create_index("ix_glossary_terms_term", "glossary_terms", ["term"])
    op.create_index("ix_glossary_terms_source_id", "glossary_terms", ["source_id"])
    op.create_index("ix_glossary_terms_search_primary", "glossary_terms", ["search_primary"])
    op.create_index("ix_glossary_terms_published_at", "glossary_terms", ["published_at"])

    op.create_table(
        "referendums",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=1000), nullable=False),
        sa.Column("official_question", sa.Text(), nullable=False),
        sa.Column(
            "referendum_type",
            sa.Enum(
                "national_abrogative",
                "constitutional",
                "regional",
                "municipal",
                "consultative",
                "other",
                name="referendumtype",
                native_enum=False,
                length=64,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "scheduled",
                "open",
                "closed",
                "cancelled",
                "completed",
                name="referendumstatus",
                native_enum=False,
                length=64,
            ),
            nullable=False,
        ),
        sa.Column("vote_date", sa.Date(), nullable=False),
        sa.Column("vote_end_date", sa.Date(), nullable=True),
        sa.Column("start_time", sa.Time(), nullable=True),
        sa.Column("end_time", sa.Time(), nullable=True),
        sa.Column("voting_hours_description", sa.Text(), nullable=True),
        sa.Column(
            "scope_type",
            sa.Enum(
                "national",
                "region",
                "municipality",
                name="geographicscopetype",
                native_enum=False,
                length=64,
            ),
            nullable=False,
        ),
        sa.Column("region_id", sa.Integer(), nullable=True),
        sa.Column("municipality_id", sa.Integer(), nullable=True),
        sa.Column("quorum_required", sa.Boolean(), nullable=True),
        sa.Column("quorum_description", sa.Text(), nullable=True),
        sa.Column("official_source_url", sa.Text(), nullable=False),
        sa.Column("voting_guide_id", sa.Integer(), nullable=True),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("search_primary", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("search_document", sa.Text(), nullable=False, server_default=""),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "("
            "(scope_type = 'national' AND region_id IS NULL AND municipality_id IS NULL) OR "
            "(scope_type = 'region' AND region_id IS NOT NULL AND municipality_id IS NULL) OR "
            "(scope_type = 'municipality' AND municipality_id IS NOT NULL)"
            ")",
            name="ck_referendums_scope",
        ),
        sa.ForeignKeyConstraint(["region_id"], ["regions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["municipality_id"], ["municipalities.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["voting_guide_id"], ["voting_guides.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_referendums_referendum_type", "referendums", ["referendum_type"])
    op.create_index("ix_referendums_status", "referendums", ["status"])
    op.create_index("ix_referendums_vote_date", "referendums", ["vote_date"])
    op.create_index("ix_referendums_scope_type", "referendums", ["scope_type"])
    op.create_index("ix_referendums_region_id", "referendums", ["region_id"])
    op.create_index("ix_referendums_municipality_id", "referendums", ["municipality_id"])
    op.create_index("ix_referendums_voting_guide_id", "referendums", ["voting_guide_id"])
    op.create_index("ix_referendums_search_primary", "referendums", ["search_primary"])
    op.create_index("ix_referendums_published_at", "referendums", ["published_at"])

    op.create_table(
        "referendum_source_identifiers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("referendum_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("official_identifier", sa.String(length=1000), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["referendum_id"], ["referendums.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id", "official_identifier", name="uq_referendum_source_identity"
        ),
    )
    op.create_index(
        "ix_referendum_source_identifiers_referendum_id",
        "referendum_source_identifiers",
        ["referendum_id"],
    )
    op.create_index(
        "ix_referendum_source_identifiers_source_id",
        "referendum_source_identifiers",
        ["source_id"],
    )

    op.create_table(
        "referendum_drafts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("referendum_id", sa.Integer(), nullable=False),
        sa.Column("raw_document_id", sa.Integer(), nullable=False),
        sa.Column("supersedes_id", sa.Integer(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum("initial", "update", name="referendumdraftkind", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "in_review",
                "approved",
                "rejected",
                "superseded",
                name="referendumdraftstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("observation_hash", sa.String(length=64), nullable=False),
        sa.Column("proposed_data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["referendum_id"], ["referendums.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["raw_document_id"], ["raw_documents.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"], ["referendum_drafts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "referendum_id",
            "observation_hash",
            name="uq_referendum_draft_observation",
        ),
    )
    op.create_index(
        "ix_referendum_drafts_referendum_id", "referendum_drafts", ["referendum_id"]
    )
    op.create_index(
        "ix_referendum_drafts_raw_document_id", "referendum_drafts", ["raw_document_id"]
    )
    op.create_index("ix_referendum_drafts_status", "referendum_drafts", ["status"])
    op.create_index(
        "ix_referendum_drafts_status_created",
        "referendum_drafts",
        ["status", "created_at"],
    )

    op.create_table(
        "referendum_evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("draft_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("raw_document_id", sa.Integer(), nullable=False),
        sa.Column("field_path", sa.String(length=500), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_field", sa.String(length=500), nullable=False),
        sa.Column("source_value", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["draft_id"], ["referendum_drafts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["raw_document_id"], ["raw_documents.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_referendum_evidence_draft_id", "referendum_evidence", ["draft_id"])
    op.create_index(
        "ix_referendum_evidence_source_id", "referendum_evidence", ["source_id"]
    )
    op.create_index(
        "ix_referendum_evidence_raw_document_id",
        "referendum_evidence",
        ["raw_document_id"],
    )

    op.create_table(
        "referendum_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("draft_id", sa.Integer(), nullable=False),
        sa.Column("reviewer", sa.String(length=200), nullable=False),
        sa.Column(
            "decision",
            sa.Enum(
                "approved",
                "rejected",
                name="referendumreviewdecision",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["draft_id"], ["referendum_drafts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_id", name="uq_referendum_review_draft"),
    )
    op.create_index("ix_referendum_reviews_draft_id", "referendum_reviews", ["draft_id"])

    op.create_table(
        "notification_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "channel",
            sa.Enum("internal", name="notificationchannel", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("destination_token", sa.String(length=64), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum(
                "referendum_upcoming",
                "voting_day_reminder",
                name="notificationeventtype",
                native_enum=False,
                length=64,
            ),
            nullable=False,
        ),
        sa.Column("referendum_id", sa.Integer(), nullable=True),
        sa.Column("region_id", sa.Integer(), nullable=True),
        sa.Column("municipality_id", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["referendum_id"], ["referendums.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["region_id"], ["regions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["municipality_id"], ["municipalities.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "channel",
            "destination_token",
            "event_type",
            "referendum_id",
            name="uq_notification_subscription_target",
        ),
    )
    op.create_index(
        "ix_notification_subscriptions_destination_token",
        "notification_subscriptions",
        ["destination_token"],
    )
    op.create_index(
        "ix_notification_subscriptions_referendum_id",
        "notification_subscriptions",
        ["referendum_id"],
    )
    op.create_index(
        "ix_notification_subscriptions_region_id",
        "notification_subscriptions",
        ["region_id"],
    )
    op.create_index(
        "ix_notification_subscriptions_municipality_id",
        "notification_subscriptions",
        ["municipality_id"],
    )

    op.create_table(
        "notification_reminder_candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("identity_key", sa.String(length=64), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum(
                "referendum_upcoming",
                "voting_day_reminder",
                name="notificationeventtype",
                native_enum=False,
                length=64,
            ),
            nullable=False,
        ),
        sa.Column("referendum_id", sa.Integer(), nullable=False),
        sa.Column("scheduled_for", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["referendum_id"], ["referendums.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("identity_key"),
    )
    op.create_index(
        "ix_notification_reminder_candidates_identity_key",
        "notification_reminder_candidates",
        ["identity_key"],
        unique=True,
    )
    op.create_index(
        "ix_notification_reminder_candidates_event_type",
        "notification_reminder_candidates",
        ["event_type"],
    )
    op.create_index(
        "ix_notification_reminder_candidates_referendum_id",
        "notification_reminder_candidates",
        ["referendum_id"],
    )
    op.create_index(
        "ix_notification_reminder_candidates_scheduled_for",
        "notification_reminder_candidates",
        ["scheduled_for"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        op.execute(
            sa.text(
                "CREATE INDEX ix_referendums_search_primary_trgm "
                "ON referendums USING gin (search_primary gin_trgm_ops)"
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX ix_glossary_terms_search_primary_trgm "
                "ON glossary_terms USING gin (search_primary gin_trgm_ops)"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("DROP INDEX IF EXISTS ix_glossary_terms_search_primary_trgm"))
        op.execute(sa.text("DROP INDEX IF EXISTS ix_referendums_search_primary_trgm"))
    op.drop_table("notification_reminder_candidates")
    op.drop_table("notification_subscriptions")
    op.drop_table("referendum_reviews")
    op.drop_table("referendum_evidence")
    op.drop_table("referendum_drafts")
    op.drop_table("referendum_source_identifiers")
    op.drop_table("referendums")
    op.drop_table("glossary_terms")
    op.drop_table("voting_guides")
