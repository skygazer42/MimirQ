/**
 * ChunkPreview 组件类型定义
 */

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
}

export interface ChunkPreviewState {
  // 文件状态
  fileList: ChunkPreviewFileItem[]
  currentFileIndex: number
  currentFile: File | null
  currentFileItem: ChunkPreviewFileItem | null
  isDragging: boolean

  // UI 状态
  isLoading: boolean
  isSubmitting: boolean
  submitSuccess: boolean
  error: string | null
  processedStatus: Record<string, 'pending' | 'success' | 'error'>

  // 预览数据
  previewData: any | null
  hoveredChunkIndex: number | null

  // 配置状态
  chunkSize: number
  chunkOverlap: number
  strategy: string

  // 外部 context
  parserBackend: string
  chunkStrategy: string
  onClose?: () => void
}

export interface ChunkPreviewActions {
  // 文件操作
  addFiles: (files: File[]) => void
  removeFile: (index: number) => void
  setCurrentFileIndex: (index: number) => void

  // UI 操作
  setIsDragging: (isDragging: boolean) => void
  setHoveredChunkIndex: (index: number | null) => void

  // 拖放处理
  handleDragOver: (e: React.DragEvent) => void
  handleDragLeave: (e: React.DragEvent) => void
  handleDrop: (e: React.DragEvent) => void

  // 数据操作
  runPreview: () => Promise<void>
  submitChunks: () => Promise<void>
  useExample: () => void
  reset: () => void

  // 配置操作
  updateSettings: (settings: Partial<Pick<ChunkPreviewState, 'chunkSize' | 'chunkOverlap' | 'strategy'>>) => void
  setParserBackend: (backend: string) => void
  setChunkStrategy: (strategy: string) => void
}

export type ChunkPreviewContextType = ChunkPreviewState & ChunkPreviewActions
