"""Add structured feedback triage and lineage fields."""

import sqlalchemy as sa

from alembic import op

revision = "0019_feedback_triage"
down_revision = "0018_dify_metadata_alias_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("message_feedback", sa.Column("category", sa.String(length=32), nullable=True))
    op.add_column("message_feedback", sa.Column("category_source", sa.String(length=32), nullable=True))
    op.add_column("message_feedback", sa.Column("query_hash", sa.String(length=64), nullable=True))
    op.add_column("message_feedback", sa.Column("retrieval_trace_ref", sa.String(length=255), nullable=True))
    op.add_column("message_feedback", sa.Column("profile", sa.String(length=64), nullable=True))
    op.add_column("message_feedback", sa.Column("judge_score_ref", sa.String(length=255), nullable=True))
    op.create_check_constraint(
        "ck_message_feedback_category",
        "message_feedback",
        "category IS NULL OR category IN ('retrieval_miss', 'wrong_answer', 'out_of_scope', 'other')",
    )
    op.create_check_constraint(
        "ck_message_feedback_category_source",
        "message_feedback",
        "category_source IS NULL OR category_source IN ('user', 'llm_auto', 'reviewer')",
    )
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_message_feedback_tenant_category",
            "message_feedback",
            ["tenant_id", "category"],
            unique=False,
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_message_feedback_tenant_category",
            table_name="message_feedback",
            postgresql_concurrently=True,
        )
    op.drop_constraint("ck_message_feedback_category_source", "message_feedback", type_="check")
    op.drop_constraint("ck_message_feedback_category", "message_feedback", type_="check")
    for column in (
        "judge_score_ref",
        "profile",
        "retrieval_trace_ref",
        "query_hash",
        "category_source",
        "category",
    ):
        op.drop_column("message_feedback", column)
