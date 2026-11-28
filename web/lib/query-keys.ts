type QueryParams = Record<string, unknown>

const DATASET_LIST_KEY = ['datasets', 'list'] as const
const DATASET_CATEGORY_ASSIGNMENTS_KEY = ['datasets', 'categories'] as const

export const queryKeys = {
  parsing: {
    librarySource: (id: string | undefined) => ['parsing', 'library-source', id] as const,
  },
  documents: {
    all: ['documents'] as const,
    list: (params?: QueryParams) => ['documents', 'list', params] as const,
    detail: (id: string) => ['documents', 'detail', id] as const,
    access: (id: string) => ['documents', 'access', id] as const,
    lifecycleMetadata: (id: string) => ['documents', 'lifecycle-metadata', id] as const,
    chunks: (id: string) => ['documents', 'chunks', id] as const,
    versions: (id: string) => ['documents', 'versions', id] as const,
    timeline: (id: string, params?: QueryParams) => ['documents', 'timeline', id, params] as const,
    health: (id: string, params?: QueryParams) => ['documents', 'health', id, params] as const,
    folders: (params?: QueryParams) => ['documents', 'folders', params] as const,
    nebula: ['documents', 'nebula'] as const,
  },
  datasets: {
    all: ['datasets'] as const,
    lists: DATASET_LIST_KEY,
    list: (params?: QueryParams) => [...DATASET_LIST_KEY, params] as const,
    exhaustive: (params?: QueryParams) => ['datasets', 'exhaustive', params] as const,
    detail: (id: string) => ['datasets', 'detail', id] as const,
    profileSummary: (id: string) => ['datasets', 'profile-summary', id] as const,
    profileScanRuns: (id: string, params?: QueryParams) => ['datasets', 'profile-scan-runs', id, params] as const,
    profileScanRunOptions: (id: string) => ['datasets', 'profile-scan-runs', id, 'options'] as const,
    profileFindingDocuments: (id: string, findingKey: string | null, params?: QueryParams) =>
      ['datasets', 'profile-finding-documents', id, findingKey, params] as const,
    profileBucketDocuments: (id: string, params?: QueryParams) =>
      ['datasets', 'profile-bucket-documents', id, params] as const,
    config: (id: string) => ['datasets', 'config', id] as const,
    health: (id: string) => ['datasets', 'health', id] as const,
    ingestionPolicy: (id: string) => ['datasets', 'ingestion-policy', id] as const,
    ingestionPolicyVersions: (id: string) => ['datasets', 'ingestion-policy-versions', id] as const,
    ingestionStats: (id: string) => ['datasets', 'ingestion-stats', id] as const,
    precheckRuns: (id: string, params?: QueryParams) => ['datasets', 'precheck-runs', id, params] as const,
    precheckSummary: (id: string, runId: string | undefined) => ['datasets', 'precheck-summary', id, runId] as const,
    precheckSamples: (id: string, runId: string | undefined, params?: QueryParams) =>
      ['datasets', 'precheck-samples', id, runId, params] as const,
    precheckNearDups: (id: string, runId: string | undefined) => ['datasets', 'precheck-near-dups', id, runId] as const,
    precheckDiff: (id: string, runId: string | undefined, params?: QueryParams) =>
      ['datasets', 'precheck-diff', id, runId, params] as const,
    precheckIngestionPolicySuggestion: (id: string, runId: string | undefined, params?: QueryParams) =>
      ['datasets', 'precheck-ingestion-policy-suggestion', id, runId, params] as const,
    precheckFindingFiles: (
      id: string,
      runId: string | undefined,
      findingKey: string | undefined,
      params?: QueryParams,
    ) => ['datasets', 'precheck-finding-files', id, runId, findingKey, params] as const,
    categoryAssignments: DATASET_CATEGORY_ASSIGNMENTS_KEY,
    categories: (id: string) => [...DATASET_CATEGORY_ASSIGNMENTS_KEY, id] as const,
    tables: (id: string, params?: QueryParams) => ['datasets', 'tables', id, params] as const,
    tableAsset: (id: string, tableId: string) => ['datasets', 'table-asset', id, tableId] as const,
    dbCatalogTables: (id: string, params?: QueryParams) => ['datasets', 'db-catalog', id, 'tables', params] as const,
    dbCatalogTableDetail: (id: string, tableId: string | null) =>
      ['datasets', 'db-catalog', id, 'table-detail', tableId] as const,
    dbCatalogProfiles: (id: string, params?: QueryParams) =>
      ['datasets', 'db-catalog', id, 'profiles', params] as const,
  },
  chat: {
    all: ['chat'] as const,
    conversationsAll: ['chat', 'conversations'] as const,
    conversations: (params?: QueryParams) => ['chat', 'conversations', params] as const,
    conversationPagesAll: ['chat', 'conversation-pages'] as const,
    conversationPages: (params?: QueryParams) => ['chat', 'conversation-pages', params] as const,
    messages: (conversationId: string, params?: QueryParams) => ['chat', 'messages', conversationId, params] as const,
    messagePages: (conversationId: string | null) => ['chat', 'message-pages', conversationId] as const,
    summary: (conversationId: string) => ['chat', 'summary', conversationId] as const,
    ragTraces: (conversationId: string, params?: QueryParams) =>
      ['chat', 'rag-traces', conversationId, params] as const,
  },
  pipeline: {
    capabilities: ['pipeline', 'capabilities'] as const,
  },
  connectors: {
    runs: (params?: QueryParams) => ['connectors', 'runs', params] as const,
  },
  groups: {
    all: ['groups'] as const,
    options: ['groups', 'list', 'options'] as const,
    list: (params?: QueryParams) => ['groups', 'list', params] as const,
    detail: (id: string) => ['groups', 'detail', id] as const,
    members: (id: string, params?: QueryParams) => ['groups', 'detail', id, 'members', params] as const,
  },
  auth: {
    all: ['auth'] as const,
    profile: ['auth', 'profile'] as const,
  },
  rbac: {
    members: (params?: QueryParams) => ['rbac', 'members', params] as const,
  },
  access: {
    current: ['access', 'current'] as const,
  },
  accessReview: {
    summary: ['access-review', 'summary'] as const,
  },
  prompts: {
    all: ['prompts'] as const,
    list: (params?: QueryParams) => ['prompts', 'list', params] as const,
  },
  ragviz: {
    similarityCollections: ['ragviz', 'similarity', 'collections'] as const,
  },
  governance: {
    all: ['governance'] as const,
    profiles: (params?: QueryParams) => ['governance', 'profiles', params] as const,
    profile: (profileRef: string) => ['governance', 'profile', profileRef] as const,
    profileResolved: (profileRef: string) => ['governance', 'profile-resolved', profileRef] as const,
  },
  industryRules: {
    rulesets: ['industry-rules', 'rulesets'] as const,
    ruleset: (name: string) => ['industry-rules', 'ruleset', name] as const,
    glossarySuggestions: (datasetId: string, ruleset: string, params?: QueryParams) =>
      ['industry-rules', 'glossary-suggestions', datasetId, ruleset, params] as const,
  },
  datasetCategories: {
    tree: ['dataset-categories', 'tree'] as const,
  },
  kg: {
    nodeDetail: (kind: string, nodeId: string | undefined, scope: QueryParams | null) =>
      ['kg', 'node-detail', kind, nodeId, scope] as const,
    predicateOntology: ['kg', 'predicate-ontology'] as const,
    entityAliases: (entityId: string | null) => ['kg', 'entity-aliases', entityId] as const,
    entityAliasSuggestions: (entityId: string | null) => ['kg', 'entity-alias-suggestions', entityId] as const,
    entityMergePreview: (request: QueryParams | null) => ['kg', 'entity-merge-preview', request] as const,
  },
  settings: {
    snapshot: ['settings', 'snapshot'] as const,
    status: ['settings', 'status'] as const,
  },
  diagnostics: {
    onlineQuality: (params?: QueryParams) => ['diagnostics', 'online-quality', params] as const,
    ready: ['diagnostics', 'ready'] as const,
    deps: ['diagnostics', 'deps'] as const,
  },
  lineage: {
    answer: (requestId: string) => ['lineage', 'answer', requestId] as const,
    chunk: (chunkId: string) => ['lineage', 'chunk', chunkId] as const,
  },
  indexAudit: {
    result: (datasetId: string | undefined) => ['indexAudit', datasetId] as const,
  },
  health: {
    status: ['health'] as const,
    ready: ['health', 'ready'] as const,
    meta: ['meta'] as const,
  },
  evaluations: {
    all: ['evaluations'] as const,
    list: (params?: QueryParams) => ['evaluations', 'list', params] as const,
    ragasRuns: (params?: QueryParams) => ['evaluations', 'ragas-runs', params] as const,
    ragasConversationReadiness: (conversationIds: string[]) =>
      ['evaluations', 'ragas-conversation-readiness', conversationIds] as const,
    ragasRunDetail: (runId: string | undefined, params?: QueryParams) =>
      ['evaluations', 'ragas-run-detail', runId, params] as const,
    regressionRuns: (params?: QueryParams) => ['evaluations', 'regression-runs', params] as const,
    regressionRunLists: ['evaluations', 'regression-runs'] as const,
    regressionCaseComparison: (baseRunId: string | undefined, targetRunId: string | undefined) =>
      ['evaluations', 'regression-case-comparison', baseRunId, targetRunId] as const,
    regressionRunDetail: (runId: string | null, params?: QueryParams) =>
      ['evaluations', 'regression-run-detail', runId, params] as const,
    querysetHealthRuns: (params?: QueryParams) => ['evaluations', 'queryset-health-runs', params] as const,
    querysetHealthDiff: (params?: QueryParams) => ['evaluations', 'queryset-health-diff', params] as const,
    regressionLeaderboard: (params?: QueryParams) => ['evaluations', 'regression-leaderboard', params] as const,
    regressionRunDiff: (targetRunId: string, params?: QueryParams) =>
      ['evaluations', 'regression-run-diff', targetRunId, params] as const,
    regressionCases: (params?: QueryParams) => ['evaluations', 'regression-cases', params] as const,
    regressionCaseLists: () => ['evaluations', 'regression-cases'] as const,
    regressionCaseWindow: (datasetId: string | null | undefined) =>
      ['evaluations', 'regression-cases', { dataset_id: datasetId, fetch_max: 1000, limit: 200 }] as const,
  },
} as const
