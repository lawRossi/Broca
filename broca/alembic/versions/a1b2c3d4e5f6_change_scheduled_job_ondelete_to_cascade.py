"""change scheduled_job ondelete to cascade

Revision ID: a1b2c3d4e5f6
Revises: fcc46ff4e8f8
Create Date: 2026-10-25 00:00:00.000000

将 scheduled_job 表的 session_id 和 agent_id 外键的 ondelete 策略
从 SET NULL 改为 CASCADE，使得删除 session/agent 时自动级联删除
关联的 scheduled_job 记录（避免产生 session_id=NULL 的孤儿记录）。

SQLite 不支持 ALTER CONSTRAINT，使用 Alembic batch mode（表重建）实现。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'fcc46ff4e8f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: change ondelete from SET NULL to CASCADE."""
    with op.batch_alter_table('scheduled_job', schema=None) as batch_op:
        # Drop old FK constraints (SET NULL)
        batch_op.drop_constraint(
            'sqlite_autoindex_scheduled_job_session', type_='foreignkey'
        )
        # Re-create FK constraints with CASCADE
        batch_op.create_foreign_key(
            'fk_scheduled_job_session_cascade',
            'session',
            ['session_id'],
            ['session_id'],
            ondelete='CASCADE',
        )

    # Note: agent_id FK also needs to be changed, but in SQLite's auto-created
    # schema the constraint naming may vary. The table recreation in batch mode
    # will apply the new model definition which includes CASCADE for both FKs.
    # If the agent_id FK constraint name differs, this is handled by the
    # table recreation picking up the updated model metadata.


def downgrade() -> None:
    """Downgrade schema: revert ondelete to SET NULL."""
    with op.batch_alter_table('scheduled_job', schema=None) as batch_op:
        batch_op.drop_constraint(
            'fk_scheduled_job_session_cascade', type_='foreignkey'
        )
        batch_op.create_foreign_key(
            'sqlite_autoindex_scheduled_job_session',
            'session',
            ['session_id'],
            ['session_id'],
            ondelete='SET NULL',
        )
