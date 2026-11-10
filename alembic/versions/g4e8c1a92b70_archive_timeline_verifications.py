"""Editorial verification of Archivio timeline drafts.

Revision ID: g4e8c1a92b70
Revises: c6f2a8e15d34
Create Date: 2026-11-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g4e8c1a92b70"
down_revision: Union[str, Sequence[str], None] = "c6f2a8e15d34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "archive_timeline_verifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("event_index", sa.Integer(), nullable=False),
        sa.Column("official_url", sa.Text(), nullable=False),
        sa.Column("official_name", sa.String(300), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("reviewed_by", sa.String(200), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_archive_timeline_verifications_slug_event",
        "archive_timeline_verifications",
        ["slug", "event_index"],
    )
    op.create_index(
        "ix_archive_timeline_verifications_slug",
        "archive_timeline_verifications",
        ["slug"],
    )
    op.create_index(
        "ix_archive_timeline_verifications_status",
        "archive_timeline_verifications",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_archive_timeline_verifications_status", table_name="archive_timeline_verifications")
    op.drop_index("ix_archive_timeline_verifications_slug", table_name="archive_timeline_verifications")
    op.drop_index("ix_archive_timeline_verifications_slug_event", table_name="archive_timeline_verifications")
    op.drop_table("archive_timeline_verifications")
