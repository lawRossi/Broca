"""add message_seq_counter table

Revision ID: 0a1b2c3d4e5f
Revises: a1b2c3d4e5f6
Create Date: 2026-11-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0a1b2c3d4e5f"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the message_seq_counter table
    op.create_table(
        "message_seq_counter",
        sa.Column("counter_key", sa.String, primary_key=True),
        sa.Column("last_seq", sa.Integer, nullable=False, server_default="0"),
    )

    # Initialize counters for existing sessions (message sequence)
    op.execute("""
        INSERT INTO message_seq_counter (counter_key, last_seq)
        SELECT DISTINCT session_id, COALESCE(MAX(sequence_number), 0)
        FROM message WHERE session_id IS NOT NULL
        GROUP BY session_id;
    """)

    # Initialize counters for existing sessions (turn sequence)
    op.execute("""
        INSERT INTO message_seq_counter (counter_key, last_seq)
        SELECT 'turn_' || session_id, COALESCE(MAX(sequence_number), 0)
        FROM turn WHERE session_id IS NOT NULL
        GROUP BY session_id
        ON CONFLICT(counter_key) DO NOTHING;
    """)


def downgrade() -> None:
    op.drop_table("message_seq_counter")
