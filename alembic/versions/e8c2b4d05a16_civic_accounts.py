"""Citizen email/password accounts for the public app.

Revision ID: e8c2b4d05a16
Revises: d5a9c3e81f07
Create Date: 2026-11-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8c2b4d05a16"
down_revision: Union[str, Sequence[str], None] = "d5a9c3e81f07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "civic_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(40), nullable=False),
        sa.Column("profile_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_civic_accounts_email", "civic_accounts", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_civic_accounts_email", table_name="civic_accounts")
    op.drop_table("civic_accounts")
