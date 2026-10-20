"""tasks: roadmap items become tasks (zone, lot, plan, result); reminders only notify; notifications know where

- roadmap_items is renamed to tasks in place: zone/lot/plan links, the bitácora entry finishing it logs
  (result_event_type), when it was done, its source. Statuses: hecho -> hecha, cancelado -> cancelada, + bloqueada.
- A reminder is a notice, never "done": pendiente -> activo; hecho/cancelado -> terminado; + pausado.
  reminder_completions and reminders.completed_at go away (the bitácora holds what was done).
- notifications get zone_id / lot_id so a reminder's notice opens where it belongs.

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-10-20 16:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e8f9a0b1c2d3'
down_revision: Union[str, None] = 'd7e8f9a0b1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EVENT_TYPES = (
    "('irrigation', 'fertilization', 'pest_control', 'sowing', 'transplant', 'harvest', 'inspection', "
    "'observation', 'soil_prep', 'amendment', 'pruning', 'weeding', 'photo')"
)


def upgrade() -> None:
    # ---- tasks
    op.drop_constraint(op.f('ck_roadmap_items_roadmap_status_valid'), 'roadmap_items', type_='check')
    op.rename_table('roadmap_items', 'tasks')
    op.execute("ALTER TABLE tasks RENAME CONSTRAINT pk_roadmap_items TO pk_tasks")
    for old, new in (
        ('fk_roadmap_items_account_id_accounts', 'fk_tasks_account_id_accounts'),
        ('fk_roadmap_items_assigned_to_users', 'fk_tasks_assigned_to_users'),
        ('fk_roadmap_items_field_id_fields', 'fk_tasks_field_id_fields'),
    ):
        op.execute(f"ALTER TABLE tasks RENAME CONSTRAINT {old} TO {new}")
    op.execute("ALTER INDEX ix_roadmap_items_account_assigned RENAME TO ix_tasks_account_assigned")
    op.execute("ALTER INDEX ix_roadmap_items_account_status RENAME TO ix_tasks_account_status")
    op.alter_column('tasks', 'target_date', new_column_name='due_date')
    op.execute("UPDATE tasks SET status = 'hecha' WHERE status = 'hecho'")
    op.execute("UPDATE tasks SET status = 'cancelada' WHERE status = 'cancelado'")
    op.create_check_constraint(
        op.f('ck_tasks_status_valid'), 'tasks', "status IN ('pendiente', 'en_curso', 'bloqueada', 'hecha', 'cancelada')"
    )
    for column, table in (('zone_id', 'field_zones'), ('lot_id', 'lots'), ('plan_id', 'crop_plans')):
        op.add_column('tasks', sa.Column(column, sa.UUID(), nullable=True))
        op.create_foreign_key(f'fk_tasks_{column}_{table}', 'tasks', table, [column], ['id'], ondelete='SET NULL')
        op.create_index(f'ix_tasks_{column}', 'tasks', [column])
    op.add_column('tasks', sa.Column('result_event_type', sa.String(length=30), nullable=True))
    op.create_check_constraint(
        op.f('ck_tasks_result_type_valid'), 'tasks', f"result_event_type IS NULL OR result_event_type IN {EVENT_TYPES}"
    )
    op.add_column('tasks', sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE tasks SET completed_at = updated_at WHERE status = 'hecha'")
    op.add_column('tasks', sa.Column('source', sa.String(length=10), server_default='user', nullable=False))
    op.create_check_constraint(op.f('ck_tasks_source_valid'), 'tasks', "source IN ('user', 'agent', 'plan')")
    op.add_column('tasks', sa.Column('created_by', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_tasks_created_by_users', 'tasks', 'users', ['created_by'], ['id'], ondelete='SET NULL')

    # ---- reminders: notices
    op.drop_constraint(op.f('ck_reminders_reminder_status_valid'), 'reminders', type_='check')
    op.execute("UPDATE reminders SET status = CASE status WHEN 'pendiente' THEN 'activo' ELSE 'terminado' END")
    op.alter_column('reminders', 'status', server_default=None)
    op.create_check_constraint(
        op.f('ck_reminders_reminder_status_valid'), 'reminders', "status IN ('activo', 'pausado', 'terminado')"
    )
    op.drop_column('reminders', 'completed_at')
    op.drop_index('ix_reminder_completions_zone_done', table_name='reminder_completions')
    op.drop_index('ix_reminder_completions_account_done', table_name='reminder_completions')
    op.drop_table('reminder_completions')

    # ---- notifications: where they belong
    op.add_column('notifications', sa.Column('zone_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_notifications_zone_id_field_zones', 'notifications', 'field_zones', ['zone_id'], ['id'], ondelete='SET NULL'
    )
    op.add_column('notifications', sa.Column('lot_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_notifications_lot_id_lots', 'notifications', 'lots', ['lot_id'], ['id'], ondelete='SET NULL')
    op.execute(
        "UPDATE notifications n SET zone_id = r.zone_id, lot_id = r.lot_id FROM reminders r "
        "WHERE n.entity_type = 'reminder' AND n.entity_id = r.id"
    )


def downgrade() -> None:
    op.drop_constraint('fk_notifications_lot_id_lots', 'notifications', type_='foreignkey')
    op.drop_column('notifications', 'lot_id')
    op.drop_constraint('fk_notifications_zone_id_field_zones', 'notifications', type_='foreignkey')
    op.drop_column('notifications', 'zone_id')

    op.create_table(
        'reminder_completions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('reminder_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('field_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('zone_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('lot_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name='fk_reminder_completions_account_id_accounts',
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reminder_id'], ['reminders.id'],
                                name='fk_reminder_completions_reminder_id_reminders', ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['field_id'], ['fields.id'], name='fk_reminder_completions_field_id_fields',
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['zone_id'], ['field_zones.id'], name='fk_reminder_completions_zone_id_field_zones',
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['lot_id'], ['lots.id'], name='fk_reminder_completions_lot_id_lots',
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['completed_by'], ['users.id'], name='fk_reminder_completions_completed_by_users',
                                ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name='pk_reminder_completions'),
    )
    op.create_index('ix_reminder_completions_zone_done', 'reminder_completions', ['zone_id', 'completed_at'])
    op.create_index('ix_reminder_completions_account_done', 'reminder_completions', ['account_id', 'completed_at'])
    op.add_column('reminders', sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint(op.f('ck_reminders_reminder_status_valid'), 'reminders', type_='check')
    op.execute("UPDATE reminders SET status = CASE status WHEN 'terminado' THEN 'hecho' ELSE 'pendiente' END")
    op.create_check_constraint(
        op.f('ck_reminders_reminder_status_valid'), 'reminders', "status IN ('pendiente', 'hecho', 'cancelado')"
    )

    op.drop_constraint('fk_tasks_created_by_users', 'tasks', type_='foreignkey')
    op.drop_column('tasks', 'created_by')
    op.drop_constraint(op.f('ck_tasks_source_valid'), 'tasks', type_='check')
    op.drop_column('tasks', 'source')
    op.drop_column('tasks', 'completed_at')
    op.drop_constraint(op.f('ck_tasks_result_type_valid'), 'tasks', type_='check')
    op.drop_column('tasks', 'result_event_type')
    for column, table in (('zone_id', 'field_zones'), ('lot_id', 'lots'), ('plan_id', 'crop_plans')):
        op.drop_index(f'ix_tasks_{column}', table_name='tasks')
        op.drop_constraint(f'fk_tasks_{column}_{table}', 'tasks', type_='foreignkey')
        op.drop_column('tasks', column)
    op.drop_constraint(op.f('ck_tasks_status_valid'), 'tasks', type_='check')
    op.execute("UPDATE tasks SET status = 'hecho' WHERE status = 'hecha'")
    op.execute("UPDATE tasks SET status = 'cancelado' WHERE status = 'cancelada'")
    op.execute("UPDATE tasks SET status = 'pendiente' WHERE status = 'bloqueada'")
    op.alter_column('tasks', 'due_date', new_column_name='target_date')
    op.execute("ALTER INDEX ix_tasks_account_status RENAME TO ix_roadmap_items_account_status")
    op.execute("ALTER INDEX ix_tasks_account_assigned RENAME TO ix_roadmap_items_account_assigned")
    for new, old in (
        ('fk_tasks_account_id_accounts', 'fk_roadmap_items_account_id_accounts'),
        ('fk_tasks_assigned_to_users', 'fk_roadmap_items_assigned_to_users'),
        ('fk_tasks_field_id_fields', 'fk_roadmap_items_field_id_fields'),
    ):
        op.execute(f"ALTER TABLE tasks RENAME CONSTRAINT {new} TO {old}")
    op.execute("ALTER TABLE tasks RENAME CONSTRAINT pk_tasks TO pk_roadmap_items")
    op.rename_table('tasks', 'roadmap_items')
    op.create_check_constraint(
        op.f('ck_roadmap_items_roadmap_status_valid'), 'roadmap_items',
        "status IN ('pendiente', 'en_curso', 'hecho', 'cancelado')",
    )
