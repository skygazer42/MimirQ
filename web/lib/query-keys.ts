type QueryParams = Record<string, unknown> | undefined

export const queryKeys = {
  documents: {
    all: ['documents'] as const,
    list: (params?: QueryParams) => ['documents', 'list', params] as const,
    detail: (id: string) => ['documents', 'detail', id] as const,
    chunks: (id: string) => ['documents', 'chunks', id] as const,
  },
  datasets: {
    all: ['datasets'] as const,
    list: (params?: QueryParams) => ['datasets', 'list', params] as const,
    detail: (id: string) => ['datasets', 'detail', id] as const,
    health: (id: string) => ['datasets', 'health', id] as const,
  },
  chat: {
    all: ['chat'] as const,
    conversations: (params?: QueryParams) => ['chat', 'conversations', params] as const,
    messages: (conversationId: string) => ['chat', 'messages', conversationId] as const,
  },
  pipeline: {
    capabilities: ['pipeline', 'capabilities'] as const,
  },
  connectors: {
    runs: (params?: QueryParams) => ['connectors', 'runs', params] as const,
  },
  auth: {
    all: ['auth'] as const,
    profile: ['auth', 'profile'] as const,
  },
  access: {
    current: ['access', 'current'] as const,
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
  },
} as const
