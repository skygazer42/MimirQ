/**
 * ChunkPreview 组件类型定义
 */

import type { ChunkPreviewResponse, JsonObject } from '@/types'
import type { ChunkPreviewRequestParams } from '@/lib/api/document-helpers'
import type { documentApi } from '@/lib/api/documents'

export type ChunkOverride = {
  content?: string
  metadata?: JsonObject
  disabled?: boolean
  updatedAt?: number
}

/** Keys are ChunkPreviewItem.index, independently of the item's position in the source array. */
export type ChunkOverrides = Record<number, ChunkOverride>
export type ChunkPreviewProcessedStatus = 'pending' | 'processing' | 'success' | 'error'

export type ChunkPreviewProps = {
  onConfirm?: (params: { chunk_size: number; chunk_overlap: number }) => void
  onClose?: () => void
}

export type ChunkPreviewFileItem = {
  id: string
  file: File
  /** Client identity for this immutable File input; one document can have multiple content revisions. */
  fileRevision: string
  displayName: string
  originalFileType?: string
  originalFileSize?: number
  /** Known source time in milliseconds: remote update, saved parse, or local import time. */
  sourceTimeMs?: number
  source: 'local_upload' | 'example' | 'parsing_workspace' | 'knowledge_base'
  datasetId?: string | null
  datasetName?: string | null
  documentId?: string | null
}

export type ChunkPreviewState = {
  // 文件状态
  fileList: ChunkPreviewFileItem[]
  currentFileIndex: number
  currentFile: File | null
  currentFileItem: ChunkPreviewFileItem | null
  isDragging: boolean

  // 数据集（可选）
  datasetId: string
  scopeSyncLoading: boolean
  scopeSyncError: string | null

  // UI 状态
  isLoading: boolean
  isSubmitting: boolean
  showOriginalPanel: boolean
  showSettingsPanel: boolean
  gapReviewRequest: number
  submitSuccess: boolean
  error: string | null
  processedStatus: Record<string, ChunkPreviewProcessedStatus>
  selectedIngestFileIds: ReadonlySet<string>
  createdDocumentId: string | null

  // 预览数据
  previewData: ChunkPreviewResponse | null
  /** Immutable File that produced previewData, independently of a later currentFile revision. */
  previewSourceFile: File | null
  // Optional per-chunk overrides (frontend-only): used for editing content/metadata before ingestion/export.
  chunkOverrides: ChunkOverrides
  /** Source-array positions; URL selection and original-view callbacks use the same positions. */
  hoveredChunkIndex: number | null
  selectedChunkIndex: number | null
  lastPreviewAt: number | null
  lastPreviewDurationMs: number | null
  cacheHit: boolean
  isPreviewDirty: boolean
  autoPreviewEnabled: boolean
  runHistory: Array<{
    id: string
    fileId: string
    fileName: string
    parserBackend: string
    strategy: string
    chunkSize: number
    chunkOverlap: number
    totalChunks: number
    durationMs: number
    createdAt: number
    cacheHit: boolean
    cacheKey?: string
  }>

  // 配置状态
  chunkSize: number
  chunkOverlap: number
  strategy: string
  // 预览载荷控制；手动入库不接受截断结果。
  includeOriginalText: boolean
  originalTextMaxChars: number
  maxChunks: number
  useParseCache: boolean
  separatorPreset: string
  separatorCustom: string
  keepSeparator: boolean
  separatorMaxChunkSize: number
  parentChildRatio: number
  parentChildMinChildSize: number

  // 外部 context
  parserBackend: string
  chunkStrategy: string
  onClose?: () => void
}

export type ChunkPreviewRunSettings = Partial<
  Pick<ChunkPreviewState, 'chunkSize' | 'chunkOverlap' | 'strategy' | 'parserBackend'>
>

type ChunkPreviewActions = {
  // 文件操作
  addFiles: (files: File[]) => void
  removeFile: (index: number) => void
  clearFiles: () => void
  setCurrentFileIndex: (index: number) => void

  // 数据集
  setDatasetId: (datasetId: string) => void
  reloadScopeDocuments: () => void

  // UI 操作
  setIsDragging: (isDragging: boolean) => void
  setHoveredChunkIndex: (position: number | null) => void
  setSelectedChunkIndex: (position: number | null) => void
  updateChunkOverride: (index: number, override: ChunkOverride) => void
  toggleChunkDisabled: (index: number) => void
  setChunksDisabled: (indices: number[], disabled: boolean) => void
  toggleIngestFileSelection: (fileId: string) => void
  clearChunkOverride: (index: number) => void
  clearAllChunkOverrides: () => void
  toggleOriginalPanel: () => void
  setOriginalPanelVisible: (visible: boolean) => void
  toggleSettingsPanel: () => void
  focusGapReview: () => void

  // 拖放处理
  handleDragOver: (e: React.DragEvent) => void
  handleDragLeave: (e: React.DragEvent) => void
  handleDrop: (e: React.DragEvent) => Promise<void>

  // 数据操作
  buildChunkPreviewRequestParams: (settings?: ChunkPreviewRunSettings) => ChunkPreviewRequestParams
  buildIngestPayload: (
    preview: ChunkPreviewResponse,
    file: ChunkPreviewFileItem,
    overrides: ChunkOverrides,
  ) => Parameters<typeof documentApi.createFromChunks>[0]
  runPreview: (options?: { force?: boolean; settings?: ChunkPreviewRunSettings }) => Promise<void>
  cancelPreview: () => void
  submitChunks: () => Promise<void>
  submitSelectedFiles: () => Promise<void>
  loadExample: () => void
  reset: () => void
  toggleAutoPreview: (enabled?: boolean) => void
  clearRunHistory: () => void
  getCachedPreview: (cacheKey: string) => ChunkPreviewResponse | null

  // 配置操作
  updateSettings: (settings: Partial<Pick<ChunkPreviewState, 'chunkSize' | 'chunkOverlap' | 'strategy'>>) => void
  updatePerfSettings: (
    settings: Partial<
      Pick<ChunkPreviewState, 'includeOriginalText' | 'originalTextMaxChars' | 'maxChunks' | 'useParseCache'>
    >,
  ) => void
  updateSeparatorSettings: (
    settings: Partial<
      Pick<ChunkPreviewState, 'separatorPreset' | 'separatorCustom' | 'keepSeparator' | 'separatorMaxChunkSize'>
    >,
  ) => void
  updateParentChildSettings: (
    settings: Partial<Pick<ChunkPreviewState, 'parentChildRatio' | 'parentChildMinChildSize'>>,
  ) => void
  setParserBackend: (backend: string) => void
  setChunkStrategy: (strategy: string) => void
}

export type ChunkPreviewContextType = ChunkPreviewState & ChunkPreviewActions
