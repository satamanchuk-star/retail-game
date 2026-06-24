"""Начальная схема: таблица game_snapshots для снимков мира.

Revision ID: 0001
Revises:
Create Date: 2026-06-24
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "game_snapshots",
        sa.Column("snapshot_key", sa.String(80), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("snapshot_key"),
    )


def downgrade() -> None:
    op.drop_table("game_snapshots")
