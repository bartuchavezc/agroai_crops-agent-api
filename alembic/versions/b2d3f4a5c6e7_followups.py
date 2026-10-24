"""followups: problems being watched, and evidence on bitácora entries

Revision ID: b2d3f4a5c6e7
Revises: a1c2e3f4b5d6
Create Date: 2026-10-24 15:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'b2d3f4a5c6e7'
down_revision: Union[str, None] = 'a1c2e3f4b5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'followups',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('field_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('fields.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('zone_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('field_zones.id', ondelete='SET NULL')),
        sa.Column('lot_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('severity', sa.String(10), nullable=False),
        sa.Column('photo_hint', sa.Text()),
        sa.Column('status', sa.String(12), nullable=False),
        sa.Column('source', sa.String(10), nullable=False),
        sa.Column('origin_report_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('reports.id', ondelete='SET NULL')),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('closed_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('pest', 'disease', 'deficiency', 'other')", name=op.f('ck_followups_kind_valid')),
        sa.CheckConstraint("status IN ('abierto', 'resuelto', 'descartado')", name=op.f('ck_followups_status_valid')),
        sa.CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name=op.f('ck_followups_severity_valid')),
        sa.CheckConstraint("source IN ('user', 'agent', 'system')", name=op.f('ck_followups_source_valid')),
    )
    op.create_index('ix_followups_account_id', 'followups', ['account_id'])
    op.create_index('ix_followups_field_status', 'followups', ['field_id', 'status'])
    op.add_column(
        'field_events',
        sa.Column('followup_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('followups.id', ondelete='SET NULL')),
    )
    op.create_index('ix_field_events_followup_id', 'field_events', ['followup_id'])
    op.add_column(
        'field_events',
        sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
    )


def downgrade() -> None:
    op.drop_column('field_events', 'evidence')
    op.drop_index('ix_field_events_followup_id', table_name='field_events')
    op.drop_column('field_events', 'followup_id')
    op.drop_index('ix_followups_field_status', table_name='followups')
    op.drop_index('ix_followups_account_id', table_name='followups')
    op.drop_table('followups')
