"""add report_type to reports

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-27 16:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'reports',
        sa.Column('report_type', sa.String(length=20), nullable=False, server_default='diagnosis'),
    )
    op.alter_column('reports', 'report_type', server_default=None)
    op.create_check_constraint(
        'ck_reports_report_type', 'reports', "report_type IN ('diagnosis', 'periodic')"
    )


def downgrade() -> None:
    op.drop_constraint('ck_reports_report_type', 'reports', type_='check')
    op.drop_column('reports', 'report_type')
