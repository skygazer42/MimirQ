/**
 * ChunkPreview 组件类型定义
 */

import type { ChunkPreviewResponse } from '@/types'

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

  // UI 状态
  isLoading: boolean
  isSubmitting: boolean
  showOriginalPanel: boolean
  showSettingsPanel: boolean
  submitSuccess: boolean
  error: string | null
  processedStatus: Record<string, 'pending' | 'success' | 'error'>
  createdDocumentId: string | null

  // 预览数据
  previewData: ChunkPreviewResponse | null
  hoveredChunkIndex: number | null
  selectedChunkIndex: number | null
  lastPreviewAt: number | null
  lastPreviewDurationMs: number | null
  cacheHit: boolean
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
  }>

  // 配置状态
  chunkSize: number
  chunkOverlap: number
  strategy: string
  separatorPreset: string
  separatorCustom: string
  keepSeparator: boolean
  separatorMaxChunkSize: number

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
  toggleOriginalPanel: () => void
  toggleSettingsPanel: () => void

  // 拖放处理
  handleDragOver: (e: React.DragEvent) => void
  handleDragLeave: (e: React.DragEvent) => void
  handleDrop: (e: React.DragEvent) => void

  // 数据操作
  runPreview: (options?: { force?: boolean }) => Promise<void>
  cancelPreview: () => void
  submitChunks: () => Promise<void>
  loadExample: () => void
  reset: () => void
  toggleAutoPreview: (enabled?: boolean) => void

  // 配置操作
  updateSettings: (settings: Partial<Pick<ChunkPreviewState, 'chunkSize' | 'chunkOverlap' | 'strategy'>>) => void
  updateSeparatorSettings: (
    settings: Partial<Pick<ChunkPreviewState, 'separatorPreset' | 'separatorCustom' | 'keepSeparator' | 'separatorMaxChunkSize'>>
  ) => void
  setParserBackend: (backend: string) => void
  setChunkStrategy: (strategy: string) => void
}

export type ChunkPreviewContextType = ChunkPreviewState & ChunkPreviewActions
