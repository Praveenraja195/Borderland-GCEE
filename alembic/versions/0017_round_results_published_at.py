"""round_results_published_at

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-19

Adds rounds.results_published_at. It is set (to now()) every time the admin
publishes final results, so it doubles as a monotonically increasing
broadcast id: team devices replay the outcome animation and acknowledge
whenever they see a value they have not seen before. It also decouples
"results are published" from rounds.status = 'COMPLETED', so completing a
round no longer fires outcomes on team screens before results are computed.
"""

from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rounds",
        sa.Column("results_published_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Rounds that were already completed before this column existed were
    # published through the old status-based gate; keep them published.
    op.execute(
        "UPDATE rounds SET results_published_at = COALESCE(end_time, now()) "
        "WHERE status = 'COMPLETED' AND results_published_at IS NULL"
    )


def downgrade() -> None:
    op.drop_column("rounds", "results_published_at")
