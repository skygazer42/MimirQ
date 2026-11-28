import { coerceOneOf } from '@/lib/one-of'

export const DATASET_ALL = '__all__'
export const TABS = ['documents', 'retrieval'] as const
export const STATUS_FILTERS = ['all', 'completed', 'processing', 'failed', 'quarantined'] as const
const LIFECYCLE_FILTERS = ['active', 'archived', 'disabled', 'all'] as const
const SORT_KEYS = ['created_at', 'filename', 'file_size'] as const
const SORT_DIRECTIONS = ['asc', 'desc'] as const

type KnowledgeTabType = (typeof TABS)[number]
type KnowledgeStatusFilter = (typeof STATUS_FILTERS)[number]
type KnowledgeLifecycleFilter = (typeof LIFECYCLE_FILTERS)[number]
type KnowledgeSortKey = (typeof SORT_KEYS)[number]
type KnowledgeSortDir = (typeof SORT_DIRECTIONS)[number]

export type KnowledgeQueryState = {
  activeTab: KnowledgeTabType
  docFilter: string
  statusFilter: KnowledgeStatusFilter
  lifecycleFilter: KnowledgeLifecycleFilter
  datasetScope: string
  folderPath: string | null
  sortKey: KnowledgeSortKey
  sortDir: KnowledgeSortDir
  connectorRunId: string | null
  tasksOpen: boolean
}

function readQueryTarget(value: string | null): string | null {
  if (value === null) return null
  const target = value.trim()
  return target.length > 0 ? target : null
}

function readQueryOption<const T extends readonly string[]>(value: string | null, options: T, defaultValue: T[number]) {
  return value === null ? defaultValue : coerceOneOf(options, value, defaultValue)
}

export function parseKnowledgeQueryState(searchParams: URLSearchParams): KnowledgeQueryState {
  const query = searchParams.get('q')
  const datasetScope = readQueryTarget(searchParams.get('dataset')) ?? DATASET_ALL
  const connectorRunId = readQueryTarget(searchParams.get('run'))

  return {
    activeTab: readQueryOption(searchParams.get('tab'), TABS, 'documents'),
    docFilter: query !== null && query.trim().length > 0 ? query : '',
    statusFilter: readQueryOption(searchParams.get('status'), STATUS_FILTERS, 'all'),
    lifecycleFilter: readQueryOption(searchParams.get('lifecycle'), LIFECYCLE_FILTERS, 'active'),
    datasetScope,
    folderPath: datasetScope === DATASET_ALL ? null : readQueryTarget(searchParams.get('folder')),
    sortKey: readQueryOption(searchParams.get('order_by'), SORT_KEYS, 'created_at'),
    sortDir: readQueryOption(searchParams.get('order_dir'), SORT_DIRECTIONS, 'desc'),
    connectorRunId,
    tasksOpen: connectorRunId !== null || searchParams.get('tasks') === '1',
  }
}

export function serializeKnowledgeQueryState(state: KnowledgeQueryState): string {
  const query = state.docFilter.trim()
  const dataset = readQueryTarget(state.datasetScope)
  const folder = readQueryTarget(state.folderPath)
  const run = readQueryTarget(state.connectorRunId)

  const params = new URLSearchParams()
  if (state.activeTab !== 'documents') params.set('tab', state.activeTab)
  if (query.length > 0) params.set('q', query)
  if (state.statusFilter !== 'all') params.set('status', state.statusFilter)
  if (state.lifecycleFilter !== 'active') params.set('lifecycle', state.lifecycleFilter)
  if (dataset !== null && dataset !== DATASET_ALL) {
    params.set('dataset', dataset)
    if (folder !== null) params.set('folder', folder)
  }
  if (state.sortKey !== 'created_at') params.set('order_by', state.sortKey)
  if (state.sortDir !== 'desc') params.set('order_dir', state.sortDir)
  if (run !== null) params.set('run', run)
  else if (state.tasksOpen) params.set('tasks', '1')
  return params.toString()
}
