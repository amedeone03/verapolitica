"""Reactions of registered readers on published posts.

Revision ID: a1f6c9d27e48
Revises: e8c2b4d05a16
Create Date: 2026-11-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1f6c9d27e48"
down_revision: Union[str, Sequence[str], None] = "e8c2b4d05a16"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "civic_post_reactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("civic_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "post_id",
            sa.Integer(),
            sa.ForeignKey("editorial_posts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reaction", sa.String(8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "post_id", name="uq_civic_post_reactions_account_post"),
    )
    op.create_index("ix_civic_post_reactions_account_id", "civic_post_reactions", ["account_id"])
    op.create_index("ix_civic_post_reactions_post_id", "civic_post_reactions", ["post_id"])


def downgrade() -> None:
    op.drop_index("ix_civic_post_reactions_post_id", table_name="civic_post_reactions")
    op.drop_index("ix_civic_post_reactions_account_id", table_name="civic_post_reactions")
    op.drop_table("civic_post_reactions")
