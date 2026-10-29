"""change scheduled_job ondelete to cascade

Revision ID: a1b2c3d4e5f6
Revises: fcc46ff4e8f8
Create Date: 2026-10-25 00:00:00.000000

将 scheduled_job 表的 session_id 和 agent_id 外键的 ondelete 策略
从 SET NULL 改为 CASCADE，使得删除 session/agent 时自动级联删除
关联的 scheduled_job 记录（避免产生 session_id=NULL 的孤儿记录）。

SQLite 不支持 ALTER CONSTRAINT，使用 Alembic batch mode（表重建）实现。

注意：SQLite 建表时若未显式命名，外键约束是匿名的（PRAGMA foreign_key_list
里 name 为空），因此不能通过约束名 drop_constraint —— 那样会抛出
``ValueError: No such constraint: 'sqlite_autoindex_scheduled_job_session'``。
这里改为反射原表并剥离所有外键后作为 batch 的 copy_from，重建时只创建
带 CASCADE 的新外键，从而不依赖任何约束命名。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'fcc46ff4e8f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = 'scheduled_job'

FK_SESSION = 'fk_scheduled_job_session_id_session'
FK_AGENT = 'fk_scheduled_job_agent_id_agent'


def _current_ondelete(bind) -> dict:
    """返回 {(column, referred_table): ondelete} 的当前外键策略。"""
    rows = bind.execute(sa.text(f'PRAGMA foreign_key_list({TABLE})')).fetchall()
    # (id, seq, table, from, to, on_update, on_delete, match)
    return {(row[3], row[2]): (row[6] or '').upper() for row in rows}


def _table_without_foreign_keys(bind) -> sa.Table:
    """反射 scheduled_job，返回一个不含任何外键约束的表定义。

    batch_alter_table 使用该定义作为 copy_from 重建新表，从而可以彻底
    丢弃 SQLite 里匿名（未命名）的旧外键约束。
    """
    src_meta = sa.MetaData()
    src = sa.Table(TABLE, src_meta, autoload_with=bind)

    dst_meta = sa.MetaData()
    columns = [
        sa.Column(
            col.name,
            col.type,
            primary_key=col.primary_key,
            nullable=col.nullable,
        )
        for col in src.columns
    ]
    return sa.Table(TABLE, dst_meta, *columns)


def _recreate(ondelete: str) -> None:
    """以指定的 ondelete 策略重建 scheduled_job 的两个外键。"""
    bind = op.get_bind()
    current = _current_ondelete(bind)

    if (
        current.get(('session_id', 'session')) == ondelete
        and current.get(('agent_id', 'agent')) == ondelete
    ):
        # 已经是目标策略，幂等跳过
        return

    copy_from = _table_without_foreign_keys(bind)
    with op.batch_alter_table(
        TABLE, copy_from=copy_from, recreate='always'
    ) as batch_op:
        batch_op.create_foreign_key(
            FK_SESSION,
            'session',
            ['session_id'],
            ['session_id'],
            ondelete=ondelete,
        )
        batch_op.create_foreign_key(
            FK_AGENT,
            'agent',
            ['agent_id'],
            ['agent_id'],
            ondelete=ondelete,
        )


def upgrade() -> None:
    """Upgrade schema: change ondelete from SET NULL to CASCADE."""
    _recreate('CASCADE')


def downgrade() -> None:
    """Downgrade schema: revert ondelete to SET NULL."""
    _recreate('SET NULL')
