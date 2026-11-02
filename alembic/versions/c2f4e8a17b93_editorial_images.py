"""Images uploaded by the redazione for feed cards.

Revision ID: c2f4e8a17b93
Revises: b9e3d2f41a60
Create Date: 2026-11-01
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c2f4e8a17b93"
down_revision: Union[str, Sequence[str], None] = "b9e3d2f41a60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "editorial_images",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("content_type", sa.String(40), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("alt", sa.String(300), nullable=True),
        sa.Column("credit", sa.String(300), nullable=True),
        sa.Column("uploaded_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_editorial_images_sha256", "editorial_images", ["sha256"])


def downgrade() -> None:
    op.drop_index("ix_editorial_images_sha256", table_name="editorial_images")
    op.drop_table("editorial_images")
