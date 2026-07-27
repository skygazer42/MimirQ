type QueryParams = Record<string, unknown> | undefined

export const queryKeys = {
  documents: {
    all: ['documents'] as const,
    list: (params?: QueryParams) => ['documents', 'list', params] as const,
    detail: (id: string) => ['documents', 'detail', id] as const,
    access: (id: string) => ['documents', 'access', id] as const,
    chunks: (id: string) => ['documents', 'chunks', id] as const,
    versions: (id: string) => ['documents', 'versions', id] as const,
    timeline: (id: string, params?: QueryParams) => ['documents', 'timeline', id, params] as const,
    health: (id: string, params?: QueryParams) => ['documents', 'health', id, params] as const,
    folders: (params?: QueryParams) => ['documents', 'folders', params] as const,
    nebula: ['documents', 'nebula'] as const,
  },
  datasets: {
    all: ['datasets'] as const,
    list: (params?: QueryParams) => ['datasets', 'list', params] as const,
    exhaustive: (params?: QueryParams) => ['datasets', 'exhaustive', params] as const,
    detail: (id: string) => ['datasets', 'detail', id] as const,
    profileSummary: (id: string) => ['datasets', 'profile-summary', id] as const,
    profileScanRuns: (id: string, params?: QueryParams) =>
      ['datasets', 'profile-scan-runs', id, params] as const,
    profileFindingDocuments: (id: string, findingKey: string, params?: QueryParams) =>
      ['datasets', 'profile-finding-documents', id, findingKey, params] as const,
    profileBucketDocuments: (id: string, params?: QueryParams) =>
      ['datasets', 'profile-bucket-documents', id, params] as const,
    config: (id: string) => ['datasets', 'config', id] as const,
    health: (id: string) => ['datasets', 'health', id] as const,
    ingestionPolicy: (id: string) => ['datasets', 'ingestion-policy', id] as const,
    ingestionPolicyVersions: (id: string) =>
      ['datasets', 'ingestion-policy-versions', id] as const,
    ingestionStats: (id: string) => ['datasets', 'ingestion-stats', id] as const,
    precheckRuns: (id: string, params?: QueryParams) =>
      ['datasets', 'precheck-runs', id, params] as const,
    precheckSamples: (id: string, runId: string, params?: QueryParams) =>
      ['datasets', 'precheck-samples', id, runId, params] as const,
    precheckNearDups: (id: string, runId: string) =>
      ['datasets', 'precheck-near-dups', id, runId] as const,
    precheckDiff: (id: string, runId: string, params?: QueryParams) =>
      ['datasets', 'precheck-diff', id, runId, params] as const,
    precheckIngestionPolicySuggestion: (id: string, runId: string, params?: QueryParams) =>
      ['datasets', 'precheck-ingestion-policy-suggestion', id, runId, params] as const,
    precheckFindingFiles: (id: string, runId: string, findingKey: string, params?: QueryParams) =>
      ['datasets', 'precheck-finding-files', id, runId, findingKey, params] as const,
    categories: (id: string) => ['datasets', 'categories', id] as const,
    tables: (id: string, params?: QueryParams) => ['datasets', 'tables', id, params] as const,
    dbCatalogTables: (id: string, params?: QueryParams) =>
      ['datasets', 'db-catalog', id, 'tables', params] as const,
    dbCatalogTableDetail: (id: string, tableId: string) =>
      ['datasets', 'db-catalog', id, 'table-detail', tableId] as const,
    dbCatalogProfiles: (id: string, params?: QueryParams) =>
      ['datasets', 'db-catalog', id, 'profiles', params] as const,
  },
  chat: {
    all: ['chat'] as const,
    conversationsAll: ['chat', 'conversations'] as const,
    conversations: (params?: QueryParams) => ['chat', 'conversations', params] as const,
    conversationPagesAll: ['chat', 'conversation-pages'] as const,
    conversationPages: (params?: QueryParams) =>
      ['chat', 'conversation-pages', params] as const,
    messages: (conversationId: string) => ['chat', 'messages', conversationId] as const,
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
    list: (params?: QueryParams) => ['groups', 'list', params] as const,
    detail: (id: string) => ['groups', 'detail', id] as const,
    members: (id: string, params?: QueryParams) =>
      ['groups', 'detail', id, 'members', params] as const,
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
  audit: {
    logs: (params?: QueryParams) => ['audit', 'logs', params] as const,
    filterOptions: ['audit', 'filter-options'] as const,
  },
  accessReview: {
    summary: ['access-review', 'summary'] as const,
  },
  usage: {
    summary: (params?: QueryParams) => ['usage', 'summary', params] as const,
    cost: (params?: QueryParams) => ['usage', 'cost', params] as const,
    quota: ['usage', 'quota'] as const,
    tenantQuotaSummary: ['usage', 'tenant-quota-summary'] as const,
  },
  prompts: {
    all: ['prompts'] as const,
    list: (params?: QueryParams) => ['prompts', 'list', params] as const,
  },
  ragviz: {
    similarityCollections: ['ragviz', 'similarity', 'collections'] as const,
  },
  governance: {
    profiles: (params?: QueryParams) => ['governance', 'profiles', params] as const,
    profileResolved: (profileRef: string) =>
      ['governance', 'profile-resolved', profileRef] as const,
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
  reports: {
    categories: ['reports', 'categories'] as const,
    dataset: (datasetId: string, params?: QueryParams) =>
      ['reports', 'dataset', datasetId, params] as const,
  },
  kg: {
    predicateOntology: ['kg', 'predicate-ontology'] as const,
  },
  settings: {
    snapshot: ['settings', 'snapshot'] as const,
    status: ['settings', 'status'] as const,
  },
  diagnostics: {
    onlineQuality: (params?: QueryParams) =>
      ['diagnostics', 'online-quality', params] as const,
    ready: ['diagnostics', 'ready'] as const,
    deps: ['diagnostics', 'deps'] as const,
  },
  lineage: {
    answer: (requestId: string) => ['lineage', 'answer', requestId] as const,
    chunk: (chunkId: string) => ['lineage', 'chunk', chunkId] as const,
  },
  indexAudit: {
    result: (datasetId: string) => ['indexAudit', datasetId] as const,
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
    ragasRunDetail: (runId: string, params?: QueryParams) =>
      ['evaluations', 'ragas-run-detail', runId, params] as const,
    regressionRuns: (params?: QueryParams) =>
      ['evaluations', 'regression-runs', params] as const,
    regressionRunDetail: (runId: string, params?: QueryParams) =>
      ['evaluations', 'regression-run-detail', runId, params] as const,
    querysetHealthRuns: (params?: QueryParams) =>
      ['evaluations', 'queryset-health-runs', params] as const,
    querysetHealthDiff: (params?: QueryParams) =>
      ['evaluations', 'queryset-health-diff', params] as const,
    regressionLeaderboard: (params?: QueryParams) =>
      ['evaluations', 'regression-leaderboard', params] as const,
    regressionRunDiff: (targetRunId: string, params?: QueryParams) =>
      ['evaluations', 'regression-run-diff', targetRunId, params] as const,
    regressionCases: (params?: QueryParams) =>
      ['evaluations', 'regression-cases', params] as const,
  },
} as const
