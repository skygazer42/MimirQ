"""Record when dispatch started so interrupted ontology actions can be reconciled."""

import sqlalchemy as sa
from alembic import op

revision = "0032_ontology_action_dispatch"
down_revision = "0031_enterprise_ontology_actions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("enterprise_ontology_action_requests", sa.Column("dispatch_started_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("enterprise_ontology_action_requests", "dispatch_started_at")
