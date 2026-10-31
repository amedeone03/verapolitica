"""Redazione console: append-only change log, change requests, news blocks.

Revision ID: b9e3d2f41a60
Revises: a4d8c1e7f310
Create Date: 2026-10-31

* ``editorial_log_entries``: every change made from the redazione console.
* ``editorial_change_requests``: withdrawals and re-classifications waiting
  for a second member.
* ``editorial_posts.blocks``: the structured blocks of the "Modello Notizia".
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b9e3d2f41a60"
down_revision: Union[str, Sequence[str], None] = "a4d8c1e7f310"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "editorial_log_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(200), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("object_kind", sa.String(40), nullable=False),
        sa.Column("object_id", sa.Integer(), nullable=True),
        sa.Column("politician_id", sa.Integer(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
    )
    op.create_index("ix_editorial_log_entries_created", "editorial_log_entries", ["created_at", "id"])
    op.create_index("ix_editorial_log_entries_object", "editorial_log_entries", ["object_kind", "object_id"])
    op.create_index("ix_editorial_log_entries_actor", "editorial_log_entries", ["actor"])
    op.create_index("ix_editorial_log_entries_action", "editorial_log_entries", ["action"])
    op.create_index("ix_editorial_log_entries_politician_id", "editorial_log_entries", ["politician_id"])

    op.create_table(
        "editorial_change_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("target_kind", sa.String(40), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("politician_id", sa.Integer(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "rejected", name="changerequeststatus", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_by", sa.String(200), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
    )
    op.create_index("ix_editorial_change_requests_status", "editorial_change_requests", ["status"])
    op.create_index(
        "ix_editorial_change_requests_politician_id", "editorial_change_requests", ["politician_id"]
    )

    with op.batch_alter_table("editorial_posts") as batch:
        batch.add_column(sa.Column("blocks", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("editorial_posts") as batch:
        batch.drop_column("blocks")
    op.drop_index("ix_editorial_change_requests_politician_id", table_name="editorial_change_requests")
    op.drop_index("ix_editorial_change_requests_status", table_name="editorial_change_requests")
    op.drop_table("editorial_change_requests")
    for name in (
        "ix_editorial_log_entries_politician_id",
        "ix_editorial_log_entries_action",
        "ix_editorial_log_entries_actor",
        "ix_editorial_log_entries_object",
        "ix_editorial_log_entries_created",
    ):
        op.drop_index(name, table_name="editorial_log_entries")
    op.drop_table("editorial_log_entries")
