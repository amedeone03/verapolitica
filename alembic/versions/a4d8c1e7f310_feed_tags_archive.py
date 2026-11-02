"""Add proposal tags, newsroom posts and the historical archive.

Revision ID: a4d8c1e7f310
Revises: f3c9a7d14e52
Create Date: 2026-10-31

* ``proposal_tags``: controlled CAP topic and dossier tags.
* ``editorial_posts``: reviewed newsroom posts for the home feed.
* ``legislatures`` (seeded from data/fixtures/archive/legislatures.json) and
  ``historical_parliament_mandates`` for the archive since 1946.
"""

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a4d8c1e7f310"
down_revision: Union[str, Sequence[str], None] = "f3c9a7d14e52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FIXTURE = Path(__file__).resolve().parents[2] / "data/fixtures/archive/legislatures.json"


def _enum(name: str, length: int, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, length=length)


def upgrade() -> None:
    op.create_table(
        "proposal_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "proposal_id",
            sa.Integer(),
            sa.ForeignKey("proposals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", _enum("proposaltagkind", 16, "topic", "dossier"), nullable=False),
        sa.Column("value", sa.String(64), nullable=False),
        sa.Column("assigned_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("proposal_id", "kind", "value", name="uq_proposal_tags_value"),
    )
    op.create_index("ix_proposal_tags_proposal_id", "proposal_tags", ["proposal_id"])
    op.create_index("ix_proposal_tags_kind_value", "proposal_tags", ["kind", "value"])

    op.create_table(
        "editorial_posts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "scope",
            _enum("feedscope", 32, "national", "region", "province", "municipality"),
            nullable=False,
        ),
        sa.Column(
            "region_id", sa.Integer(), sa.ForeignKey("regions.id", ondelete="RESTRICT"), nullable=True
        ),
        sa.Column("province_abbreviation", sa.String(2), nullable=True),
        sa.Column(
            "municipality_id",
            sa.Integer(),
            sa.ForeignKey("municipalities.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column(
            "corrects_id",
            sa.Integer(),
            sa.ForeignKey("editorial_posts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "status",
            _enum("editorialpoststatus", 32, "pending", "published", "rejected"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("reviewed_by", sa.String(200), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(scope <> 'region' OR region_id IS NOT NULL)"
            " AND (scope <> 'province' OR province_abbreviation IS NOT NULL)"
            " AND (scope <> 'municipality' OR municipality_id IS NOT NULL)",
            name="ck_editorial_posts_scope_target",
        ),
    )
    for column in ("scope", "region_id", "province_abbreviation", "municipality_id", "status", "published_at"):
        op.create_index(f"ix_editorial_posts_{column}", "editorial_posts", [column])

    legislatures = op.create_table(
        "legislatures",
        sa.Column("number", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("number >= 0", name="ck_legislatures_number"),
        sa.CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_legislatures_dates"),
    )
    op.create_table(
        "historical_parliament_mandates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_id", sa.Integer(), sa.ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "raw_document_id",
            sa.Integer(),
            sa.ForeignKey("raw_documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("chamber", _enum("chamber", 16, "camera", "senato", "costituente"), nullable=False),
        sa.Column(
            "legislature",
            sa.Integer(),
            sa.ForeignKey("legislatures.number", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("official_identifier", sa.String(500), nullable=False),
        sa.Column("person_identifier", sa.String(500), nullable=False),
        sa.Column("given_name", sa.String(200), nullable=False),
        sa.Column("family_name", sa.String(200), nullable=False),
        sa.Column("gender", sa.String(16), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("election_area", sa.String(300), nullable=True),
        sa.Column("group_name", sa.String(500), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column(
            "politician_id",
            sa.Integer(),
            sa.ForeignKey("politicians.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "source_id", "official_identifier", name="uq_historical_mandates_source_identifier"
        ),
    )
    op.create_index(
        "ix_historical_mandates_leg_chamber",
        "historical_parliament_mandates",
        ["legislature", "chamber"],
    )
    op.create_index(
        "ix_historical_mandates_name", "historical_parliament_mandates", ["family_name", "given_name"]
    )
    for column in ("raw_document_id", "person_identifier", "politician_id"):
        op.create_index(
            f"ix_historical_parliament_mandates_{column}", "historical_parliament_mandates", [column]
        )

    now = datetime.now(timezone.utc)
    records = json.loads(FIXTURE.read_text(encoding="utf-8"))["records"]
    op.bulk_insert(
        legislatures,
        [
            {
                "number": item["number"],
                "start_date": date.fromisoformat(item["start_date"]),
                "end_date": date.fromisoformat(item["end_date"]) if item["end_date"] else None,
                "source_url": item["source_url"],
                "created_at": now,
                "updated_at": now,
            }
            for item in records
        ],
    )


def downgrade() -> None:
    op.drop_table("historical_parliament_mandates")
    op.drop_table("legislatures")
    op.drop_table("editorial_posts")
    op.drop_table("proposal_tags")
