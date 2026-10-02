"""ai analyses

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_analyses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("verdict", sa.String(length=10), nullable=False),
        sa.Column("confidence", sa.String(length=10), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_ai_analyses_run_id_runs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_analyses")),
        sa.UniqueConstraint("run_id", "signature", name=op.f("uq_ai_analyses_run_id")),
    )
    op.create_index(op.f("ix_ai_analyses_run_id"), "ai_analyses", ["run_id"], unique=False)
    # Autogenerate proposed adding this column as NOT NULL with no default,
    # which fails on a table that already has rows. Added with a default,
    # filled in for existing rows, then the default is dropped again.
    op.add_column(
        "differences", sa.Column("signature", sa.Text(), nullable=False, server_default="")
    )
    op.execute(
        r"""
        UPDATE differences
        SET signature = kind || ':' || regexp_replace(path, '\[(\d+|[^\]]*=[^\]]*)\]', '[*]', 'g')
        """
    )
    op.alter_column("differences", "signature", server_default=None)
    op.add_column("runs", sa.Column("ai_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "ai_error")
    op.drop_column("differences", "signature")
    op.drop_index(op.f("ix_ai_analyses_run_id"), table_name="ai_analyses")
    op.drop_table("ai_analyses")
