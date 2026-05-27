"""add_message_execution_id

Revision ID: 8a3f2c1b5d7e
Revises: 0772c86c3a46
Create Date: 2026-05-26 20:30:00.000000

在 Message 表添加 execution_id 字段，用于编排执行消息关联。
普通会话消息该字段为 NULL，不影响原有逻辑。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '8a3f2c1b5d7e'
down_revision: Union[str, Sequence[str], None] = '0772c86c3a46'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """给 message 表添加 execution_id 列（可为空，不影响普通会话）"""
    with op.batch_alter_table('message', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('execution_id', sa.String(), nullable=True)
        )
        batch_op.create_index(
            op.f('ix_message_execution_id'),
            ['execution_id'],
            unique=False,
        )


def downgrade() -> None:
    """回滚：删除 execution_id 列"""
    with op.batch_alter_table('message', schema=None) as batch_op:
        batch_op.drop_index(op.f('ix_message_execution_id'))
        batch_op.drop_column('execution_id')
