export type KnowledgeTabType = 'documents' | 'retrieval' | 'settings'
export type KnowledgeViewMode = 'grid' | 'list'
export type KnowledgeStatusFilter = 'all' | 'completed' | 'processing' | 'failed' | 'quarantined'
export type KnowledgeLifecycleFilter = 'active' | 'archived' | 'disabled' | 'all'
export type KnowledgeSortKey = 'created_at' | 'filename' | 'file_size'
export type KnowledgeSortDir = 'asc' | 'desc'

export type KnowledgeQueryState = {
  activeTab: KnowledgeTabType
  viewMode: KnowledgeViewMode
  docFilter: string
  statusFilter: KnowledgeStatusFilter
  lifecycleFilter: KnowledgeLifecycleFilter
  datasetScope: string
  folderPath: string | null
  sortKey: KnowledgeSortKey
  sortDir: KnowledgeSortDir
}

const DEFAULT_DATASET_ALL = '__all__'

export function parseKnowledgeQueryState(
  searchParams: URLSearchParams,
  opts?: { datasetAllValue?: string }
): KnowledgeQueryState {
  const DATASET_ALL = opts?.datasetAllValue ?? DEFAULT_DATASET_ALL

  const state: KnowledgeQueryState = {
    activeTab: 'documents',
    viewMode: 'grid',
    docFilter: '',
    statusFilter: 'all',
    lifecycleFilter: 'active',
    datasetScope: DATASET_ALL,
    folderPath: null,
    sortKey: 'created_at',
    sortDir: 'desc',
  }

  const tab = searchParams.get('tab')
  if (tab === 'documents' || tab === 'retrieval' || tab === 'settings') state.activeTab = tab

  const view = searchParams.get('view')
  if (view === 'grid' || view === 'list') state.viewMode = view

  const q = searchParams.get('q')
  if (typeof q === 'string' && q.trim()) state.docFilter = q

  const status = searchParams.get('status')
  if (status === 'all' || status === 'completed' || status === 'processing' || status === 'failed' || status === 'quarantined') {
    state.statusFilter = status
  }

  const lifecycle = searchParams.get('lifecycle')
  if (lifecycle === 'active' || lifecycle === 'archived' || lifecycle === 'disabled' || lifecycle === 'all') {
    state.lifecycleFilter = lifecycle
  }

  const dataset = searchParams.get('dataset')
  if (dataset && dataset.trim()) state.datasetScope = dataset

  const folder = searchParams.get('folder')
  if (folder && folder.trim() && dataset && dataset.trim() && dataset !== DATASET_ALL) state.folderPath = folder.trim()

  const orderBy = searchParams.get('order_by')
  if (orderBy === 'created_at' || orderBy === 'filename' || orderBy === 'file_size') state.sortKey = orderBy

  const orderDir = searchParams.get('order_dir')
  if (orderDir === 'asc' || orderDir === 'desc') state.sortDir = orderDir

  return state
}

export function serializeKnowledgeQueryState(
  state: KnowledgeQueryState,
  opts?: { datasetAllValue?: string }
): string {
  const DATASET_ALL = opts?.datasetAllValue ?? DEFAULT_DATASET_ALL

  const params = new URLSearchParams()
  if (state.activeTab !== 'documents') params.set('tab', state.activeTab)
  if (state.viewMode !== 'grid') params.set('view', state.viewMode)
  if (state.docFilter.trim()) params.set('q', state.docFilter.trim())
  if (state.statusFilter !== 'all') params.set('status', state.statusFilter)
  if (state.lifecycleFilter !== 'active') params.set('lifecycle', state.lifecycleFilter)
  if (state.datasetScope !== DATASET_ALL) params.set('dataset', state.datasetScope)
  if (state.datasetScope !== DATASET_ALL && state.folderPath) params.set('folder', state.folderPath)
  if (state.sortKey !== 'created_at') params.set('order_by', state.sortKey)
  if (state.sortDir !== 'desc') params.set('order_dir', state.sortDir)
  return params.toString()
}

