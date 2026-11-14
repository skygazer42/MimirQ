"""Build API v1 routes when the application registers them."""

from functools import cache

from fastapi import APIRouter

_DATASETS_PREFIX = "/datasets"
_RETRIEVAL_PREFIX = "/retrieval"


@cache
def get_router() -> APIRouter:
    """Return the shared router, importing route modules only when requested."""
    from app.api.v1 import (
        audit,
        auth,
        chat,
        chunk_presets,
        connectors,
        dataset_analysis,
        dataset_categories,
        dataset_precheck,
        dataset_tables,
        datasets,
        db_catalog,
        documents,
        evaluations,
        evidence,
        evidence_capsules,
        feedback,
        governance,
        groups,
        health,
        industry_rules,
        ingestion_runs,
        integrations_conversations,
        integrations_dify,
        lineage,
        meta,
        network_analysis,
        observability,
        parsing,
        pipeline,
        prompt_templates,
        rag,
        rag_config_templates,
        ragviz,
        rbac,
        reports,
        retrieval_config_hash,
        retrieval_explain,
        retrieval_profiles,
        rtbf,
        scim,
        settings,
        usage,
    )
    from app.rag.kg.api import routes as kg

    router = APIRouter()
    router.include_router(health.router, tags=["Health"])
    router.include_router(meta.router, tags=["Meta"])
    router.include_router(auth.router, prefix="/auth", tags=["Auth"])
    router.include_router(documents.router, prefix="/documents", tags=["Documents"])
    router.include_router(parsing.router, prefix="/parsing", tags=["Parsing Workspace"])
    router.include_router(chunk_presets.router, prefix="/chunk-presets", tags=["Chunk Preview"])
    router.include_router(chat.router, prefix="/chat", tags=["Chat"])
    router.include_router(datasets.router, prefix=_DATASETS_PREFIX, tags=["Datasets"])
    router.include_router(dataset_analysis.router, prefix=_DATASETS_PREFIX, tags=["Dataset Analysis"])
    router.include_router(dataset_precheck.router, prefix=_DATASETS_PREFIX, tags=["Datasets Precheck"])
    router.include_router(dataset_tables.router, prefix=_DATASETS_PREFIX, tags=["Dataset Tables (TAG)"])
    router.include_router(db_catalog.router, prefix=_DATASETS_PREFIX, tags=["DB Catalog"])
    router.include_router(dataset_categories.router, prefix="/dataset-categories", tags=["Dataset Categories"])
    router.include_router(kg.router, prefix="/kg", tags=["Knowledge Graph (KG)"])
    router.include_router(network_analysis.router, prefix="/kg/network", tags=["Knowledge Graph (KG)"])
    router.include_router(evidence.router, prefix="/evidence", tags=["Evidence Workbench"])
    router.include_router(evidence_capsules.router, prefix="/evidence", tags=["Evidence Capsules"])
    router.include_router(settings.router, prefix="/settings", tags=["Settings"])
    router.include_router(governance.router, prefix="/governance", tags=["Governance"])
    router.include_router(evaluations.router, prefix="/evaluations", tags=["Evaluations"])
    router.include_router(prompt_templates.router, prefix="/prompt-templates", tags=["Prompt Templates"])
    router.include_router(rag_config_templates.router, prefix="/rag-config-templates", tags=["RAG Config Templates"])
    router.include_router(feedback.router, prefix="/feedback", tags=["Feedback"])
    router.include_router(industry_rules.router, prefix="/industry-rules", tags=["Industry Rules"])
    router.include_router(lineage.router, prefix="/lineage", tags=["Lineage"])
    router.include_router(pipeline.router, prefix="/pipeline", tags=["Pipeline"])
    router.include_router(connectors.router, prefix="/connectors", tags=["Connectors"])
    router.include_router(ingestion_runs.router, prefix="/ingestion", tags=["Ingestion Runs"])
    router.include_router(
        integrations_conversations.router,
        prefix="/integrations/conversations",
        tags=["External Conversation Integration"],
    )
    router.include_router(integrations_dify.router, prefix="/integrations/dify", tags=["Dify Integration"])
    router.include_router(rag.router, prefix="/rag", tags=["RAG"])
    router.include_router(retrieval_profiles.router, prefix=_RETRIEVAL_PREFIX, tags=["Retrieval"])
    router.include_router(retrieval_explain.router, prefix=_RETRIEVAL_PREFIX, tags=["Retrieval"])
    router.include_router(retrieval_config_hash.router, prefix=_RETRIEVAL_PREFIX, tags=["Retrieval"])
    router.include_router(ragviz.router, prefix="/ragviz", tags=["RAG Visualization (RAGViz)"])
    router.include_router(groups.router, prefix="/groups", tags=["Groups"])
    router.include_router(rbac.router, prefix="/rbac", tags=["RBAC"])
    router.include_router(scim.router, prefix="/scim/v2", tags=["SCIM v2"])
    router.include_router(reports.router, prefix="/reports", tags=["Reports"])
    router.include_router(observability.router, prefix="/observability", tags=["Observability"])
    router.include_router(rtbf.router, prefix="/rtbf", tags=["RTBF"])
    router.include_router(audit.router, prefix="/audit", tags=["Audit"])
    router.include_router(usage.router, prefix="/usage", tags=["Usage"])
    return router


__all__ = ["get_router"]
