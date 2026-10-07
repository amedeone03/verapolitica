"""Add pledge classification, fulfilment assessment and audit tables.

Revision ID: d1a7e5b94c30
Revises: c8d5f3b02a21
Create Date: 2026-10-07

Additive schema for the pledge scorecard (methodology pledge-score/v1):
editorial classification, proposed and published fulfilment verdicts with
reviewer approvals, and blind audit samples/codings. No existing table changes.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1a7e5b94c30'
down_revision: Union[str, Sequence[str], None] = 'c8d5f3b02a21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('pledge_audit_samples',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('sample_key', sa.String(length=100), nullable=False),
    sa.Column('seed', sa.Integer(), nullable=False),
    sa.Column('population_size', sa.Integer(), nullable=False),
    sa.Column('inclusion_probability', sa.Float(), nullable=False),
    sa.Column('population_ids', sa.JSON(), nullable=False),
    sa.Column('assessment_ids', sa.JSON(), nullable=False),
    sa.Column('created_by', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('sample_key', name='uq_pledge_audit_sample_key')
    )
    op.create_table('pledge_classifications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('proposal_id', sa.Integer(), nullable=False),
    sa.Column('specificity', sa.Enum('high', 'medium', 'vague', name='pledgespecificity', native_enum=False, length=32), nullable=False),
    sa.Column('commitment_type', sa.Enum('action', 'outcome', name='commitmenttype', native_enum=False, length=32), nullable=False),
    sa.Column('holder_role', sa.Enum('government_single_party', 'government_coalition', 'opposition', 'unknown', name='holderrole', native_enum=False, length=32), nullable=False),
    sa.Column('cap_topic_code', sa.String(length=16), nullable=True),
    sa.Column('mandate_start', sa.Date(), nullable=True),
    sa.Column('mandate_end', sa.Date(), nullable=True),
    sa.Column('classified_by', sa.String(length=200), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('mandate_end IS NULL OR mandate_start IS NULL OR mandate_end >= mandate_start', name='ck_pledge_classification_mandate_dates'),
    sa.ForeignKeyConstraint(['proposal_id'], ['proposals.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('proposal_id', name='uq_pledge_classification_proposal')
    )
    with op.batch_alter_table('pledge_classifications', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_pledge_classifications_cap_topic_code'), ['cap_topic_code'], unique=False)
        batch_op.create_index(batch_op.f('ix_pledge_classifications_holder_role'), ['holder_role'], unique=False)
        batch_op.create_index(batch_op.f('ix_pledge_classifications_proposal_id'), ['proposal_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_pledge_classifications_specificity'), ['specificity'], unique=False)

    op.create_table('pledge_assessment_drafts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('proposal_id', sa.Integer(), nullable=False),
    sa.Column('origin', sa.Enum('evidence_matcher', 'editor', name='pledgeassessmentorigin', native_enum=False, length=32), nullable=False),
    sa.Column('status', sa.Enum('pending', 'awaiting_second_approval', 'approved', 'rejected', name='pledgeassessmentdraftstatus', native_enum=False, length=32), nullable=False),
    sa.Column('proposed_verdict', sa.Enum('not_yet_rated', 'in_progress', 'stalled', 'kept', 'partially_kept', 'broken', name='fulfillmentverdict', native_enum=False, length=32), nullable=False),
    sa.Column('evidence_label', sa.Enum('supports', 'refutes', 'not_enough_info', name='evidencelabel', native_enum=False, length=32), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=False),
    sa.Column('quoted_excerpt', sa.Text(), nullable=False),
    sa.Column('source_url', sa.Text(), nullable=False),
    sa.Column('raw_document_id', sa.Integer(), nullable=False),
    sa.Column('document_chunk_id', sa.Integer(), nullable=True),
    sa.Column('effective_at', sa.Date(), nullable=True),
    sa.Column('retrieval', sa.JSON(), nullable=True),
    sa.Column('judge_name', sa.String(length=100), nullable=True),
    sa.Column('judge_version', sa.String(length=100), nullable=True),
    sa.Column('created_by', sa.String(length=200), nullable=False),
    sa.Column('identity_key', sa.String(length=64), nullable=False),
    sa.Column('rejection_note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['document_chunk_id'], ['document_chunks.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['proposal_id'], ['proposals.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['raw_document_id'], ['raw_documents.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('proposal_id', 'identity_key', name='uq_pledge_assessment_draft_key')
    )
    with op.batch_alter_table('pledge_assessment_drafts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_pledge_assessment_drafts_proposal_id'), ['proposal_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_pledge_assessment_drafts_raw_document_id'), ['raw_document_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_pledge_assessment_drafts_status'), ['status'], unique=False)
        batch_op.create_index('ix_pledge_assessment_drafts_status_created', ['status', 'created_at'], unique=False)

    op.create_table('pledge_assessment_approvals',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('draft_id', sa.Integer(), nullable=False),
    sa.Column('reviewer', sa.String(length=200), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['draft_id'], ['pledge_assessment_drafts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('draft_id', 'reviewer', name='uq_pledge_assessment_approval_reviewer')
    )
    with op.batch_alter_table('pledge_assessment_approvals', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_pledge_assessment_approvals_draft_id'), ['draft_id'], unique=False)

    op.create_table('pledge_assessments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('proposal_id', sa.Integer(), nullable=False),
    sa.Column('draft_id', sa.Integer(), nullable=False),
    sa.Column('verdict', sa.Enum('not_yet_rated', 'in_progress', 'stalled', 'kept', 'partially_kept', 'broken', name='fulfillmentverdict', native_enum=False, length=32), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=False),
    sa.Column('quoted_excerpt', sa.Text(), nullable=False),
    sa.Column('source_url', sa.Text(), nullable=False),
    sa.Column('raw_document_id', sa.Integer(), nullable=False),
    sa.Column('effective_at', sa.Date(), nullable=True),
    sa.Column('approved_by', sa.JSON(), nullable=False),
    sa.Column('methodology_version', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['draft_id'], ['pledge_assessment_drafts.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['proposal_id'], ['proposals.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['raw_document_id'], ['raw_documents.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('draft_id', name='uq_pledge_assessment_draft')
    )
    with op.batch_alter_table('pledge_assessments', schema=None) as batch_op:
        batch_op.create_index('ix_pledge_assessments_proposal_created', ['proposal_id', 'created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_pledge_assessments_proposal_id'), ['proposal_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_pledge_assessments_raw_document_id'), ['raw_document_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_pledge_assessments_verdict'), ['verdict'], unique=False)

    op.create_table('pledge_audit_codings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('sample_id', sa.Integer(), nullable=False),
    sa.Column('assessment_id', sa.Integer(), nullable=False),
    sa.Column('coder', sa.String(length=200), nullable=False),
    sa.Column('verdict', sa.Enum('not_yet_rated', 'in_progress', 'stalled', 'kept', 'partially_kept', 'broken', name='fulfillmentverdict', native_enum=False, length=32), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['assessment_id'], ['pledge_assessments.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['sample_id'], ['pledge_audit_samples.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('sample_id', 'assessment_id', 'coder', name='uq_pledge_audit_coding_coder')
    )
    with op.batch_alter_table('pledge_audit_codings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_pledge_audit_codings_assessment_id'), ['assessment_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_pledge_audit_codings_sample_id'), ['sample_id'], unique=False)



def downgrade() -> None:
    op.drop_table("pledge_audit_codings")
    op.drop_table("pledge_assessments")
    op.drop_table("pledge_assessment_approvals")
    op.drop_table("pledge_assessment_drafts")
    op.drop_table("pledge_classifications")
    op.drop_table("pledge_audit_samples")
