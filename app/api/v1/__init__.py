"""
API v1 routes.
"""


from importlib import import_module

from fastapi import APIRouter

_ROUTER: APIRouter | None = None
_DATASETS_PREFIX = "/datasets"
_RETRIEVAL_PREFIX = "/retrieval"


def _build_router() -> APIRouter:
    audit = import_module("app.api.v1.audit")
    auth = import_module("app.api.v1.auth")
    chat = import_module("app.api.v1.chat")
    chunk_presets = import_module("app.api.v1.chunk_presets")
    connectors = import_module("app.api.v1.connectors")
    dataset_categories = import_module("app.api.v1.dataset_categories")
    dataset_analysis = import_module("app.api.v1.dataset_analysis")
    dataset_precheck = import_module("app.api.v1.dataset_precheck")
    dataset_tables = import_module("app.api.v1.dataset_tables")
    datasets = import_module("app.api.v1.datasets")
    db_catalog = import_module("app.api.v1.db_catalog")
    documents = import_module("app.api.v1.documents")
    evaluations = import_module("app.api.v1.evaluations")
    evidence = import_module("app.api.v1.evidence")
    evidence_capsules = import_module("app.api.v1.evidence_capsules")
    feedback = import_module("app.api.v1.feedback")
    governance = import_module("app.api.v1.governance")
    groups = import_module("app.api.v1.groups")
    health = import_module("app.api.v1.health")
    ingestion_runs = import_module("app.api.v1.ingestion_runs")
    integrations_conversations = import_module("app.api.v1.integrations_conversations")
    integrations_dify = import_module("app.api.v1.integrations_dify")
    industry_rules = import_module("app.api.v1.industry_rules")
    lineage = import_module("app.api.v1.lineage")
    ltr = import_module("app.api.v1.ltr")
    meta = import_module("app.api.v1.meta")
    network_analysis = import_module("app.api.v1.network_analysis")
    observability = import_module("app.api.v1.observability")
    parsing = import_module("app.api.v1.parsing")
    pipeline = import_module("app.api.v1.pipeline")
    prompt_templates = import_module("app.api.v1.prompt_templates")
    rag = import_module("app.api.v1.rag")
    rag_config_templates = import_module("app.api.v1.rag_config_templates")
    ragviz = import_module("app.api.v1.ragviz")
    rbac = import_module("app.api.v1.rbac")
    reports = import_module("app.api.v1.reports")
    retrieval_config_hash = import_module("app.api.v1.retrieval_config_hash")
    retrieval_explain = import_module("app.api.v1.retrieval_explain")
    retrieval_profiles = import_module("app.api.v1.retrieval_profiles")
    scim = import_module("app.api.v1.scim")
    settings = import_module("app.api.v1.settings")
    rtbf = import_module("app.api.v1.rtbf")
    usage = import_module("app.api.v1.usage")
    kg = import_module("app.rag.kg.api.routes")

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
    router.include_router(ltr.router, prefix="/ltr", tags=["LTR"])
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


def get_router() -> APIRouter:
    global _ROUTER
    if _ROUTER is None:
        _ROUTER = _build_router()
    return _ROUTER


def __getattr__(name: str):
    if name == "router":
        router = get_router()
        globals()["router"] = router
        return router

    # Convenience: allow `app.api.v1.<submodule>` attribute access so callers and
    # tests can use dotted paths like `app.api.v1.dataset_precheck.*` without
    # importing the submodule eagerly.
    try:
        mod = import_module(f"{__name__}.{name}")
    except ModuleNotFoundError as exc:
        # Only translate to AttributeError when the *submodule itself* is missing.
        if str(getattr(exc, "name", "") or "") in {f"{__name__}.{name}", name}:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
        raise

    globals()[name] = mod
    return mod


__all__ = ["get_router", "router"]
