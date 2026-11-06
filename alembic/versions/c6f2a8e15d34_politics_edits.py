"""Editorial corrections to the Politica page.

Revision ID: c6f2a8e15d34
Revises: b4e1d7c93a52
Create Date: 2026-11-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c6f2a8e15d34"
down_revision: Union[str, Sequence[str], None] = "b4e1d7c93a52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "politics_edits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(120), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("reviewed_by", sa.String(200), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_politics_edits_key", "politics_edits", ["key"])
    op.create_index("ix_politics_edits_status", "politics_edits", ["status"])


def downgrade() -> None:
    op.drop_index("ix_politics_edits_status", table_name="politics_edits")
    op.drop_index("ix_politics_edits_key", table_name="politics_edits")
    op.drop_table("politics_edits")
