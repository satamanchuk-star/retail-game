"""Таблица leaderboard_snapshots: персист зала славы между рестартами.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "leaderboard_snapshots",
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
    op.drop_table("leaderboard_snapshots")
