"""Durable run queue: stage, progress, attempts, cancellation and worker leases.

Adds to ``pipeline_runs``: ``stage``, ``progress`` (JSON counts),
``attempts``, ``lost_leases`` (queue-internal: how often the run's worker
stopped unexpectedly), ``cancel_requested``, ``worker_id``,
``lease_expires_at`` and ``started_at``, plus an index on ``created_at``
(the queue's first-in, first-out order).

Runs are now executed by a worker that holds a renewable lease, so a run
interrupted by a restart is resumed. Runs left ``pending`` or ``running`` by
the previous in-request background tasks were lost with their process; they
are marked failed with an explanation rather than started unexpectedly.
Succeeded runs get stage ``done``.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "pipeline_runs"
_INDEX = "ix_pipeline_runs_created_at"
_LOST = "interrupted by a restart before runs could be resumed; start it again"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns(_TABLE)}
    indexes = {i["name"] for i in inspector.get_indexes(_TABLE)}
    with op.batch_alter_table(_TABLE) as batch:
        if "stage" not in columns:
            batch.add_column(
                sa.Column("stage", sa.String(16), nullable=False, server_default="queued")
            )
        if "progress" not in columns:
            batch.add_column(
                sa.Column("progress", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
            )
        if "attempts" not in columns:
            batch.add_column(
                sa.Column("attempts", sa.Integer(), nullable=False, server_default="0")
            )
        if "lost_leases" not in columns:
            batch.add_column(
                sa.Column("lost_leases", sa.Integer(), nullable=False, server_default="0")
            )
        if "cancel_requested" not in columns:
            batch.add_column(
                sa.Column(
                    "cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()
                )
            )
        if "worker_id" not in columns:
            batch.add_column(sa.Column("worker_id", sa.String(64), nullable=True))
        if "lease_expires_at" not in columns:
            batch.add_column(
                sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)
            )
        if "started_at" not in columns:
            batch.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        if _INDEX not in indexes:
            batch.create_index(_INDEX, ["created_at"])

    runs = sa.table(
        _TABLE,
        sa.column("status", sa.String),
        sa.column("stage", sa.String),
        sa.column("error", sa.Text),
        sa.column("finished_at", sa.DateTime(timezone=True)),
    )
    op.execute(runs.update().where(runs.c.status == "succeeded").values(stage="done"))
    op.execute(
        runs.update()
        .where(runs.c.status.in_(("pending", "running")))
        .values(status="failed", error=_LOST, finished_at=sa.func.now())
    )


def downgrade() -> None:
    runs = sa.table(_TABLE, sa.column("status", sa.String))
    # The previous schema has no cancelled state.
    op.execute(runs.update().where(runs.c.status == "cancelled").values(status="failed"))
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_index(_INDEX)
        batch.drop_column("started_at")
        batch.drop_column("lease_expires_at")
        batch.drop_column("worker_id")
        batch.drop_column("cancel_requested")
        batch.drop_column("lost_leases")
        batch.drop_column("attempts")
        batch.drop_column("progress")
        batch.drop_column("stage")
