"""Enforce unique run-document attachments for ingestion manifests.

Duplicate-row cleanup is irreversible. Downgrade only removes the uniqueness
constraint and cannot restore deleted attachment rows or prior run stats.
"""

from alembic import op

revision = "0024_ingestion_run_doc_unique"
down_revision = "0023_document_dedup_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        WITH normalized AS (
            SELECT id,
                   tenant_id,
                   run_id,
                   document_id,
                   created_at,
                   lower(COALESCE(NULLIF(trim(status), ''), 'unknown')) AS normalized_status
            FROM ingestion_run_documents
        ),
        ranked AS (
            SELECT id,
                   tenant_id,
                   run_id,
                   normalized_status,
                   row_number() OVER (
                       PARTITION BY tenant_id, run_id, document_id
                       ORDER BY CASE normalized_status
                                    WHEN 'completed' THEN 0
                                    WHEN 'failed' THEN 1
                                    WHEN 'quarantined' THEN 2
                                    WHEN 'cancelled' THEN 3
                                    WHEN 'processing' THEN 4
                                    WHEN 'pending' THEN 5
                                    ELSE 6
                                END,
                                created_at DESC NULLS LAST,
                                id DESC
                   ) AS position
            FROM normalized
        ),
        deleted AS (
            DELETE FROM ingestion_run_documents
            WHERE id IN (SELECT id FROM ranked WHERE position > 1)
            RETURNING tenant_id, run_id
        ),
        affected_runs AS (
            SELECT DISTINCT tenant_id, run_id
            FROM deleted
        ),
        per_status AS (
            SELECT ranked.tenant_id,
                   ranked.run_id,
                   ranked.normalized_status,
                   count(*)::int AS status_total
            FROM ranked
            JOIN affected_runs
              ON affected_runs.tenant_id = ranked.tenant_id
             AND affected_runs.run_id = ranked.run_id
            WHERE ranked.position = 1
            GROUP BY ranked.tenant_id, ranked.run_id, ranked.normalized_status
        ),
        aggregates AS (
            SELECT affected_runs.tenant_id,
                   affected_runs.run_id,
                   COALESCE(sum(per_status.status_total), 0)::int AS total_documents,
                   COALESCE(
                       jsonb_object_agg(per_status.normalized_status, per_status.status_total)
                           FILTER (WHERE per_status.normalized_status IS NOT NULL),
                       '{}'::jsonb
                   ) AS status_counts
            FROM affected_runs
            LEFT JOIN per_status
              ON per_status.tenant_id = affected_runs.tenant_id
             AND per_status.run_id = affected_runs.run_id
            GROUP BY affected_runs.tenant_id, affected_runs.run_id
        )
        UPDATE ingestion_runs
        SET stats = jsonb_set(
            jsonb_set(
                jsonb_set(
                    COALESCE(ingestion_runs.stats, '{}'::jsonb),
                    '{total_documents}',
                    to_jsonb(aggregates.total_documents),
                    true
                ),
                '{status_counts}',
                aggregates.status_counts,
                true
            ),
            '{progress}',
            to_jsonb(
                CASE
                    WHEN aggregates.total_documents <= 0 THEN 0
                    ELSE LEAST(
                        100,
                        GREATEST(
                            0,
                            (
                                (
                                    COALESCE((aggregates.status_counts ->> 'completed')::int, 0)
                                    + COALESCE((aggregates.status_counts ->> 'failed')::int, 0)
                                    + COALESCE((aggregates.status_counts ->> 'quarantined')::int, 0)
                                    + COALESCE((aggregates.status_counts ->> 'cancelled')::int, 0)
                                ) * 100
                            ) / aggregates.total_documents
                        )
                    )
                END
            ),
            true
        )
        FROM aggregates
        WHERE ingestion_runs.tenant_id = aggregates.tenant_id
          AND ingestion_runs.id = aggregates.run_id
        """
    )
    op.create_unique_constraint(
        "uq_ingestion_run_documents_tenant_run_document",
        "ingestion_run_documents",
        ["tenant_id", "run_id", "document_id"],
    )


def downgrade() -> None:
    # Irreversible: deleted duplicate rows and recomputed stats are not restored.
    op.drop_constraint(
        "uq_ingestion_run_documents_tenant_run_document",
        "ingestion_run_documents",
        type_="unique",
    )
