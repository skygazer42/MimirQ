"""Build API v1 routes when the application registers them."""

from functools import cache

from fastapi import APIRouter

_DATASETS_PREFIX = "/datasets"
_RETRIEVAL_PREFIX = "/retrieval"


@cache
def get_router() -> APIRouter:
    """Return the shared router, importing route modules only when requested."""
    import app.api.v1.knowledge_graph.routes as kg
    from app.api.v1.connectors import routes as connectors
    from app.api.v1.conversations import feedback
    from app.api.v1.conversations import prompts as prompt_templates
    from app.api.v1.conversations import routes as chat
    from app.api.v1.datasets import analysis as dataset_analysis
    from app.api.v1.datasets import categories as dataset_categories
    from app.api.v1.datasets import db_catalog, reports
    from app.api.v1.datasets import precheck as dataset_precheck
    from app.api.v1.datasets import routes as datasets
    from app.api.v1.datasets import tables as dataset_tables
    from app.api.v1.documents import ingestion_runs, lineage
    from app.api.v1.documents import routes as documents
    from app.api.v1.evaluation import evidence, evidence_capsules
    from app.api.v1.evaluation import routes as evaluations
    from app.api.v1.identity import auth, groups, rbac, scim
    from app.api.v1.integrations import conversations as integrations_conversations
    from app.api.v1.integrations import dify as integrations_dify
    from app.api.v1.knowledge_graph import enterprise_ontology
    from app.api.v1.knowledge_graph import network as network_analysis
    from app.api.v1.pipelines import chunk_presets, governance, industry_rules, parsing
    from app.api.v1.pipelines import routes as pipeline
    from app.api.v1.retrieval import config_hash as retrieval_config_hash
    from app.api.v1.retrieval import config_templates as rag_config_templates
    from app.api.v1.retrieval import explain as retrieval_explain
    from app.api.v1.retrieval import profiles as retrieval_profiles
    from app.api.v1.retrieval import routes as rag
    from app.api.v1.retrieval import visualization as ragviz
    from app.api.v1.system import audit, health, meta, observability, rtbf, settings, usage

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
    router.include_router(enterprise_ontology.router, prefix="/kg/ontologies", tags=["Enterprise Ontology"])
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
