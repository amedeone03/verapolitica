"""Approved logos of parties and coats of arms of regions and provinces.

Revision ID: d5a9c3e81f07
Revises: c2f4e8a17b93
Create Date: 2026-11-01
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5a9c3e81f07"
down_revision: Union[str, Sequence[str], None] = "c2f4e8a17b93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "editorial_symbols",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("key", sa.String(40), nullable=False),
        sa.Column("image_id", sa.Integer(), sa.ForeignKey("editorial_images.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("credit", sa.String(300), nullable=False),
        sa.Column("license", sa.String(100), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("proposed_by", sa.String(200), nullable=False),
        sa.Column("approved_by", sa.String(200), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("kind", "key", name="uq_editorial_symbols_kind_key"),
    )


def downgrade() -> None:
    op.drop_table("editorial_symbols")
