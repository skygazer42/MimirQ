"""Inputs and owned outcomes for query planning; no engine or runtime context."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping, Protocol
from uuid import UUID

QueryVariant = tuple[str, str]

if TYPE_CHECKING:
    from app.rag.retrieval.orchestration.query_contract import QueryContractNormalizationOutput
    from app.rag.retrieval.orchestration.query_variants import QueryVariantStageOutput


@dataclass(frozen=True)
class RewriteSettings:
    enabled: bool
    strategy: str
    temperature: float
    max_chars: int


@dataclass(frozen=True)
class SparseQuerySettings:
    enabled: bool
    provider: str


@dataclass(frozen=True)
class IndustryQuerySettings:
    enabled: bool
    rulesets: str | Sequence[str] | None
    max_aliases: int
    max_query_chars: int


@dataclass(frozen=True)
class QueryPreparationRequest:
    question: str
    history_text: str
    rewrite: RewriteSettings
    sparse: SparseQuerySettings
    industry: IndustryQuerySettings
    temporal_enabled: bool


@dataclass(frozen=True)
class QueryPreparationOverrides:
    enable_rewrite: bool | None = None
    rewrite_strategy: str | None = None
    rewrite_temperature: float | None = None
    rewrite_max_chars: int | None = None
    sparse_enabled: bool | None = None
    sparse_provider: str | None = None
    industry_enabled: bool | None = None
    industry_rulesets: str | Sequence[str] | None = None


class RewriteModel(Protocol):
    model_name: str | None

    def invoke(self, *, question: str, history: str) -> str: ...


class RewriteModels(Protocol):
    def rewrite(self, *, strategy_id: str, temperature: float) -> RewriteModel: ...


class AsyncRewriteModel(Protocol):
    model_name: str | None

    async def ainvoke(self, *, question: str, history: str) -> str: ...


class AsyncRewriteModels(Protocol):
    def rewrite(self, *, strategy_id: str, temperature: float) -> AsyncRewriteModel: ...


class QueryVariantModels(Protocol):
    def multi_query(self, *, count: int, temperature: float) -> "TextQueryModel": ...

    def hyde(self, *, temperature: float) -> "TextQueryModel": ...

    def step_back(self, *, temperature: float) -> "TextQueryModel": ...

    def decompose(self, *, max_questions: int, temperature: float) -> "TextQueryModel": ...


class TextQueryModel(Protocol):
    model_name: str | None

    def invoke(self, *, query: str) -> str: ...


class QueryModels(RewriteModels, QueryVariantModels, Protocol):
    pass


class AsyncTextQueryModel(Protocol):
    model_name: str | None

    async def ainvoke(self, *, query: str) -> str: ...


class AsyncQueryVariantModels(Protocol):
    def multi_query(self, *, count: int, temperature: float) -> AsyncTextQueryModel: ...

    def hyde(self, *, temperature: float) -> AsyncTextQueryModel: ...

    def step_back(self, *, temperature: float) -> AsyncTextQueryModel: ...

    def decompose(self, *, max_questions: int, temperature: float) -> AsyncTextQueryModel: ...


class AsyncQueryModels(AsyncRewriteModels, AsyncQueryVariantModels, Protocol):
    pass


@dataclass(frozen=True)
class RewriteConfiguration:
    strategy_id: str
    strategy_hash: str
    temperature: float
    max_chars: int


@dataclass(frozen=True)
class RewriteOutcome:
    query: str
    used: bool
    elapsed_sec: float
    model_used: str | None
    configuration: RewriteConfiguration | None
    failure: Exception | None = None
    attempted: bool = False

    @property
    def enabled(self) -> bool:
        return self.configuration is not None

    @property
    def strategy_id(self) -> str | None:
        return self.configuration.strategy_id if self.configuration is not None else None

    @property
    def strategy_hash(self) -> str | None:
        return self.configuration.strategy_hash if self.configuration is not None else None


@dataclass(frozen=True)
class IndustryQueryOutcome:
    query: str
    metadata: dict[str, Any]
    failure: Exception | None = None


@dataclass(frozen=True)
class TemporalQueryOutcome:
    enabled: bool
    metadata: dict[str, Any]
    failure: Exception | None = None


@dataclass(frozen=True)
class PreparedQuery:
    rewrite: RewriteOutcome
    sparse: SparseQuerySettings
    industry: IndustryQueryOutcome
    temporal: TemporalQueryOutcome

    @property
    def query(self) -> str:
        return self.industry.query


@dataclass(frozen=True)
class AliasQuerySettings:
    enabled: bool
    aliases: dict[str, list[str]] | None
    max_queries: int


@dataclass(frozen=True)
class DeterministicExpansionRequest:
    query: str
    alias: AliasQuerySettings


@dataclass(frozen=True)
class AliasQueryOutcome:
    queries: list[str]
    metadata: dict[str, Any]
    elapsed_sec: float


@dataclass(frozen=True)
class DictionaryQueryOutcome:
    expansions: list[dict[str, Any]]
    metadata: dict[str, Any]
    elapsed_sec: float
    failure: Exception | None = None


@dataclass(frozen=True)
class DeterministicQueryExpansions:
    alias: AliasQueryOutcome
    dictionary: DictionaryQueryOutcome


@dataclass(frozen=True)
class KGQueryScope:
    tenant_id: UUID | None
    account_id: str | None
    document_ids: tuple[UUID, ...] | None = None
    dataset_id: UUID | None = None
    dataset_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True)
class KGQueryRequest:
    query: str
    scope: KGQueryScope


@dataclass(frozen=True)
class KGExpansionSettings:
    enabled: bool
    service_enabled: bool
    max_entities: int
    max_queries: int
    min_weight: float
    exclude_types: tuple[str, ...]


@dataclass(frozen=True)
class KGQueryExpansion:
    enabled: bool
    queries: list[str]
    entity_names: list[str]
    entities_total: int
    entities_selected: int
    elapsed_sec: float
    response: dict[str, Any] | None
    failure: Exception | None = None

    @property
    def used(self) -> bool:
        return bool(self.queries)


@dataclass(frozen=True)
class MultiQueryExperiment:
    key: str | None
    variant: str | None
    seed: int | str | None
    forced: bool


@dataclass(frozen=True)
class MultiQuerySettings:
    enabled: bool
    count: int
    temperature: float
    max_chars: int
    experiment: MultiQueryExperiment


@dataclass(frozen=True)
class TextQuerySettings:
    enabled: bool
    temperature: float
    max_chars: int
    output_max_chars: int


@dataclass(frozen=True)
class DecompositionSettings:
    enabled: bool
    max_questions: int
    min_chars: int
    max_chars: int
    temperature: float
    heuristic_enabled: bool
    model_api_key_present: bool


@dataclass(frozen=True)
class ModelQuerySettings:
    multi_query: MultiQuerySettings
    hyde: TextQuerySettings
    step_back: TextQuerySettings
    decomposition: DecompositionSettings


@dataclass(frozen=True)
class ModelQueryOverrides:
    enable_multi_query: bool | None = None
    multi_query_count: int | None = None
    multi_query_temperature: float | None = None
    multi_query_max_chars: int | None = None
    enable_hyde: bool | None = None
    enable_query_decomposition: bool | None = None
    multi_query_ab_test_key: str | None = None
    multi_query_ab_variant: str | None = None
    multi_query_ab_seed: int | str | None = None


@dataclass(frozen=True)
class ModelQueryRequest:
    query: str
    retrieval_mode: str
    settings: ModelQuerySettings


@dataclass(frozen=True)
class QueryListOutcome:
    enabled: bool
    queries: list[str]
    elapsed_sec: float
    model_used: str | None
    parse_metadata: dict[str, Any]
    failure: Exception | None = None

    @property
    def used(self) -> bool:
        return bool(self.queries)


@dataclass(frozen=True)
class TextQueryOutcome:
    enabled: bool
    text: str
    elapsed_sec: float
    model_used: str | None
    failure: Exception | None = None

    @property
    def used(self) -> bool:
        return bool(self.text)


@dataclass(frozen=True)
class StepBackQueryOutcome:
    enabled: bool
    text: str
    elapsed_sec: float
    model_used: str | None
    parse_metadata: dict[str, Any]
    failure: Exception | None = None

    @property
    def used(self) -> bool:
        return bool(self.text)


@dataclass(frozen=True)
class ModelQueryExpansions:
    multi_query: QueryListOutcome
    hyde: TextQueryOutcome
    step_back: StepBackQueryOutcome
    decomposition: QueryListOutcome
    elapsed_sec: float


@dataclass(frozen=True)
class QueryExpansionBudget:
    max_queries: int
    max_candidates: int
    token_budget: int
    latency_budget_ms: float


@dataclass(frozen=True)
class RetrievalRequest:
    preparation: QueryPreparationRequest
    options: Mapping[str, Any]
    budget: QueryExpansionBudget


@dataclass(frozen=True)
class QueryRoutingDecision:
    normalization: "QueryContractNormalizationOutput"
    evidence_contract: Mapping[str, Any]
    intent_metadata: dict[str, Any]
    adaptive_metadata: dict[str, Any]
    channel_metadata: dict[str, Any]
    effective_options: Mapping[str, Any]
    option_updates: Mapping[str, Any]


@dataclass(frozen=True)
class StreamQueryRoutingDecision:
    routing: QueryRoutingDecision
    complexity_overrides: Mapping[str, Any]
    recall_bucket: str | None = None


@dataclass(frozen=True)
class QueryExpansionRequest:
    prepared: PreparedQuery
    routing: QueryRoutingDecision
    budget: QueryExpansionBudget
    model_retrieval_mode: str
    multi_query_last: bool = False


@dataclass(frozen=True)
class QueryPlan:
    prepared: PreparedQuery
    routing: QueryRoutingDecision
    deterministic: DeterministicQueryExpansions
    kg: KGQueryExpansion
    models: ModelQueryExpansions
    variant_stage: "QueryVariantStageOutput"
    clause_queries: list[str]
    lightweight_queries: list[str]
    model_settings: ModelQuerySettings
    alias_settings: AliasQuerySettings

    @property
    def query(self) -> str:
        return self.prepared.query

    @property
    def queries(self) -> list[QueryVariant]:
        return self.variant_stage.retrieval_queries

    @property
    def retriever_options(self) -> Mapping[str, Any]:
        return self.routing.normalization.retriever_update
