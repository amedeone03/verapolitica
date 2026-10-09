"""Add unpublished pledge evidence candidate table.

Revision ID: e2b8f6c03d41
Revises: d1a7e5b94c30
Create Date: 2026-10-09

Internal official-evidence candidates used by the pledge matcher. Candidates
never publish a fulfilment verdict.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e2b8f6c03d41"
down_revision: Union[str, Sequence[str], None] = "d1a7e5b94c30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pledge_evidence_candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("proposal_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("raw_document_id", sa.Integer(), nullable=False),
        sa.Column("document_chunk_id", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_title", sa.String(length=500), nullable=True),
        sa.Column("published_at", sa.Date(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exact_excerpt", sa.Text(), nullable=False),
        sa.Column("retrieval_reason", sa.String(length=200), nullable=False),
        sa.Column("deterministic_score", sa.Float(), nullable=False),
        sa.Column("evidence_label_candidate", sa.String(length=32), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "retrieved",
                "rejected",
                "judged",
                "drafted",
                "abstained",
                name="pledgeevidencecandidatestatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("retrieval", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_chunk_id"], ["document_chunks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["proposal_id"], ["proposals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["raw_document_id"], ["raw_documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "proposal_id", "document_chunk_id", name="uq_pledge_evidence_candidate_chunk"
        ),
    )
    with op.batch_alter_table("pledge_evidence_candidates", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_pledge_evidence_candidates_document_chunk_id"),
            ["document_chunk_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_pledge_evidence_candidates_proposal_id"),
            ["proposal_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_pledge_evidence_candidates_raw_document_id"),
            ["raw_document_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_pledge_evidence_candidates_source_id"),
            ["source_id"],
            unique=False,
        )
        batch_op.create_index("ix_pledge_evidence_candidates_status", ["status"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("pledge_evidence_candidates", schema=None) as batch_op:
        batch_op.drop_index("ix_pledge_evidence_candidates_status")
        batch_op.drop_index(batch_op.f("ix_pledge_evidence_candidates_source_id"))
        batch_op.drop_index(batch_op.f("ix_pledge_evidence_candidates_raw_document_id"))
        batch_op.drop_index(batch_op.f("ix_pledge_evidence_candidates_proposal_id"))
        batch_op.drop_index(batch_op.f("ix_pledge_evidence_candidates_document_chunk_id"))
    op.drop_table("pledge_evidence_candidates")
