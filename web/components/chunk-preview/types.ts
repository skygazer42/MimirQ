/**
 * ChunkPreview 组件类型定义
 */

import type { ChunkPreviewResponse, JsonObject } from '@/types'

export interface ChunkOverride {
  content?: string
  metadata?: JsonObject
  disabled?: boolean
  updatedAt?: number
}

export type ChunkOverrides = Record<number, ChunkOverride>

export interface ChunkPreviewProps {
  onConfirm?: (params: { chunk_size: number; chunk_overlap: number }) => void
  onClose?: () => void
}

export type ChunkPreviewFileItem = {
  id: string
  file: File
  displayName: string
  originalFileType?: string
  originalFileSize?: number
  addedAt?: number
  source?: 'local_upload' | 'example' | 'parsing_workspace' | 'knowledge_base'
  datasetId?: string | null
  datasetName?: string | null
  documentId?: string | null
}

export interface ChunkPreviewState {
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
  submitSuccess: boolean
  error: string | null
  processedStatus: Record<string, 'pending' | 'success' | 'error'>
  selectedIngestFileIds: Set<string>
  createdDocumentId: string | null

  // 预览数据
  previewData: ChunkPreviewResponse | null
  // Optional per-chunk overrides (frontend-only): used for editing content/metadata before ingestion/export.
  chunkOverrides: ChunkOverrides
  hoveredChunkIndex: number | null
  selectedChunkIndex: number | null
  lastPreviewAt: number | null
  lastPreviewDurationMs: number | null
  cacheHit: boolean
  isPreviewDirty: boolean
  autoPreviewEnabled: boolean
  runHistory: Array<{
    id: string
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
  // 预览性能/载荷控制（仅影响预览，不影响入库）
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

export interface ChunkPreviewActions {
  // 文件操作
  addFiles: (files: File[]) => void
  removeFile: (index: number) => void
  clearFiles: () => void
  setCurrentFileIndex: (index: number) => void

  // 数据集
  setDatasetId: (datasetId: string) => void

  // UI 操作
  setIsDragging: (isDragging: boolean) => void
  setHoveredChunkIndex: (index: number | null) => void
  setSelectedChunkIndex: (index: number | null) => void
  updateChunkOverride: (index: number, override: ChunkOverride) => void
  toggleChunkDisabled: (index: number) => void
  setChunksDisabled: (indices: number[], disabled: boolean) => void
  toggleIngestFileSelection: (fileId: string) => void
  clearChunkOverride: (index: number) => void
  clearAllChunkOverrides: () => void
  toggleOriginalPanel: () => void
  setOriginalPanelVisible: (visible: boolean) => void
  toggleSettingsPanel: () => void

  // 拖放处理
  handleDragOver: (e: React.DragEvent) => void
  handleDragLeave: (e: React.DragEvent) => void
  handleDrop: (e: React.DragEvent) => void

  // 数据操作
  runPreview: (options?: { force?: boolean }) => Promise<void>
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
    settings: Partial<Pick<ChunkPreviewState, 'includeOriginalText' | 'originalTextMaxChars' | 'maxChunks' | 'useParseCache'>>
  ) => void
  updateSeparatorSettings: (
    settings: Partial<Pick<ChunkPreviewState, 'separatorPreset' | 'separatorCustom' | 'keepSeparator' | 'separatorMaxChunkSize'>>
  ) => void
  updateParentChildSettings: (
    settings: Partial<Pick<ChunkPreviewState, 'parentChildRatio' | 'parentChildMinChildSize'>>
  ) => void
  setParserBackend: (backend: string) => void
  setChunkStrategy: (strategy: string) => void
}

export type ChunkPreviewContextType = ChunkPreviewState & ChunkPreviewActions
