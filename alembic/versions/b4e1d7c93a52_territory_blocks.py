"""Redazione blocks for regione, provincia and comune schede.

Revision ID: b4e1d7c93a52
Revises: f3a7c9d21b48
Create Date: 2026-11-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4e1d7c93a52"
down_revision: Union[str, Sequence[str], None] = "f3a7c9d21b48"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "territory_blocks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("territory_kind", sa.String(16), nullable=False),
        sa.Column("territory_key", sa.String(16), nullable=False),
        sa.Column("block", sa.String(32), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("reviewed_by", sa.String(200), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in ("territory_kind", "territory_key", "block", "status"):
        op.create_index(f"ix_territory_blocks_{column}", "territory_blocks", [column])


def downgrade() -> None:
    for column in ("status", "block", "territory_key", "territory_kind"):
        op.drop_index(f"ix_territory_blocks_{column}", table_name="territory_blocks")
    op.drop_table("territory_blocks")
