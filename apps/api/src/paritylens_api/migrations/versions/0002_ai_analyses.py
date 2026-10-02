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


# Rows are given their signature this many at a time.
_BATCH = 5000


def _backfill_signatures() -> None:
    """Give existing differences the signature new ones are stored with.

    Done in Python, with the function the application uses, and not as a
    SQL regular expression: the path grammar has quoted keys such as
    $['a=b'] and $['x[0]'] that a regex gets wrong, and a signature that
    differs between old and new rows would split one finding in two.
    """
    from paritylens_engine.paths import generalize_text

    connection = op.get_bind()
    differences = sa.table(
        "differences",
        sa.column("id", sa.Uuid()),
        sa.column("kind", sa.String()),
        sa.column("path", sa.Text()),
        sa.column("signature", sa.Text()),
    )
    while True:
        rows = connection.execute(
            sa.select(differences.c.id, differences.c.kind, differences.c.path)
            .where(differences.c.signature == "")
            .limit(_BATCH)
        ).all()
        if not rows:
            return
        connection.execute(
            sa.update(differences)
            .where(differences.c.id == sa.bindparam("row_id"))
            .values(signature=sa.bindparam("value")),
            [
                {"row_id": row.id, "value": f"{row.kind}:{generalize_text(row.path) or row.path}"}
                for row in rows
            ],
        )


def upgrade() -> None:
    op.create_table(
        "ai_analyses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
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
    )
    op.create_index(op.f("ix_ai_analyses_run_id"), "ai_analyses", ["run_id"], unique=False)
    op.create_index(
        "uq_ai_analyses_finding",
        "ai_analyses",
        ["run_id", sa.text("md5(signature)"), "severity"],
        unique=True,
    )
    # Autogenerate proposed adding this column as NOT NULL with no default,
    # which fails on a table that already has rows. Added with a default,
    # filled in for existing rows, then the default is dropped again.
    op.add_column(
        "differences", sa.Column("signature", sa.Text(), nullable=False, server_default="")
    )
    _backfill_signatures()
    op.alter_column("differences", "signature", server_default=None)
    op.add_column("runs", sa.Column("ai_error", sa.Text(), nullable=True))
    op.add_column("runs", sa.Column("ai_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "runs", sa.Column("ai_attempts", sa.Integer(), server_default="0", nullable=False)
    )
    op.create_index(
        "ix_runs_ai_pending",
        "runs",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("ai_status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_runs_ai_pending", table_name="runs", postgresql_where=sa.text("ai_status = 'pending'")
    )
    op.drop_column("runs", "ai_attempts")
    op.drop_column("runs", "ai_started_at")
    op.drop_column("runs", "ai_error")
    op.drop_column("differences", "signature")
    op.drop_index("uq_ai_analyses_finding", table_name="ai_analyses")
    op.drop_index(op.f("ix_ai_analyses_run_id"), table_name="ai_analyses")
    op.drop_table("ai_analyses")
