"""Separate controversies from judicial proceedings on the scheda.

A controversy is a matter of public interest that does not necessarily put the
politician under investigation (a statement, a bust, a relative under
investigation). Existing rows become controversies when none of their types
concerns the politician in court.

Revision ID: f3a7c9d21b48
Revises: a1f6c9d27e48
Create Date: 2026-11-05
"""

import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3a7c9d21b48"
down_revision: Union[str, Sequence[str], None] = "a1f6c9d27e48"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_IN_COURT = {"judicial_proceeding", "investigation"}


def upgrade() -> None:
    op.add_column(
        "politician_proceedings",
        sa.Column("category", sa.String(20), nullable=False, server_default="proceeding"),
    )
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, proceeding_types FROM politician_proceedings")).fetchall()
    for row_id, types in rows:
        values = types if isinstance(types, list) else json.loads(types or "[]")
        if values and not set(values) & _IN_COURT:
            connection.execute(
                sa.text("UPDATE politician_proceedings SET category = 'controversy' WHERE id = :id"),
                {"id": row_id},
            )


def downgrade() -> None:
    op.drop_column("politician_proceedings", "category")
