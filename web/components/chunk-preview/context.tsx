/**
 * ChunkPreview Context
 * 管理切片预览的状态和业务逻辑
 */
'use client'

import { createContext, useContext, useState, useCallback, useRef, useEffect, useMemo, ReactNode } from 'react'
import { toast } from 'sonner'
import { documentApi } from '@/lib/api-client'
import { formatApiError } from '@/lib/api-errors'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { useParsedFiles } from '@/store/use-parsed-files-store'
import { getChunkStrategyLabel } from '@/lib/chunk-strategies'
import { getParserLabel } from '@/lib/parser-options'
import type { ChunkPreviewResponse } from '@/types'
import type { ChunkPreviewState, ChunkPreviewActions, ChunkPreviewFileItem, ChunkPreviewContextType } from './types'
import { EXAMPLE_TEXT } from './constants'
import { scanFiles } from './utils/file-scanner'

const ChunkPreviewContext = createContext<ChunkPreviewContextType | null>(null)
const STORAGE_DATASET_ID_KEY = 'mimirq_chunk_preview_dataset_id'
const STORAGE_SEPARATOR_SETTINGS_KEY = 'mimirq_chunk_preview_separator_settings'
const STORAGE_FOCUS_FILE_ID_KEY = 'mimirq_chunk_preview_focus_file_id'

function decodeSeparatorInput(raw: string) {
  const value = (raw || '').trim()
  if (!value) return ''
  try {
    return JSON.parse(`"${value.replace(/"/g, '\\"')}"`)
  } catch {
    return value
  }
}

export function useChunkPreview() {
  const context = useContext(ChunkPreviewContext)
  if (!context) {
    throw new Error('useChunkPreview must be used within ChunkPreviewProvider')
  }
  return context
}

interface ChunkPreviewProviderProps {
  children: ReactNode
  onConfirm?: (params: { chunk_size: number; chunk_overlap: number }) => void
  onClose?: () => void
}

export function ChunkPreviewProvider({ children, onConfirm, onClose }: ChunkPreviewProviderProps) {
  // 外部依赖
  const parsedFiles = useParsedFiles((state) => state.files)
  const { parserBackend, setParserBackend } = useParserBackendPreference()
  const { chunkStrategy, setChunkStrategy } = useChunkStrategyPreference()
  const { enabled: pipelineOverridesEnabled, options: pipelineOptions, updateOption } = usePipelineOptions()
  const { capabilities, parserBackendAvailable, chunkStrategyAvailable } = usePipelineCapabilities()

  // 生成 ID 工具
  const makeId = useCallback(
    () =>
      (typeof crypto !== 'undefined' && 'randomUUID' in crypto && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : Math.random().toString(36).slice(2)),
    []
  )

  // 核心状态
  const [fileList, setFileList] = useState<ChunkPreviewFileItem[]>([])
  const [currentFileIndex, setCurrentFileIndex] = useState<number>(0)
  const [isDragging, setIsDragging] = useState(false)

  const [isLoading, setIsLoading] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [showOriginalPanel, setShowOriginalPanel] = useState(true)
  const [showSettingsPanel, setShowSettingsPanel] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [createdDocumentId, setCreatedDocumentId] = useState<string | null>(null)

  const [datasetId, setDatasetIdState] = useState<string>('')

  const [previewData, setPreviewData] = useState<ChunkPreviewResponse | null>(null)
  const [hoveredChunkIndex, setHoveredChunkIndex] = useState<number | null>(null)
  const [selectedChunkIndex, setSelectedChunkIndex] = useState<number | null>(null)
  const [lastPreviewAt, setLastPreviewAt] = useState<number | null>(null)
  const [lastPreviewDurationMs, setLastPreviewDurationMs] = useState<number | null>(null)
  const [cacheHit, setCacheHit] = useState(false)
  const [lastPreviewCacheKey, setLastPreviewCacheKey] = useState<string | null>(null)
  const [autoPreviewEnabled, setAutoPreviewEnabled] = useState(true)
  const [runHistory, setRunHistory] = useState<Array<{
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
  }>>([])

  const [chunkSize, setChunkSize] = useState(pipelineOptions.chunk_size ?? 1000)
  const [chunkOverlap, setChunkOverlap] = useState(pipelineOptions.chunk_overlap ?? 200)
  const [separatorPreset, setSeparatorPreset] = useState('paragraph')
  const [separatorCustom, setSeparatorCustom] = useState('\\n\\n')
  const [keepSeparator, setKeepSeparator] = useState(true)
  const [separatorMaxChunkSize, setSeparatorMaxChunkSize] = useState(0)

  // 其他状态
  const [processedStatus, setProcessedStatus] = useState<Record<string, 'pending' | 'success' | 'error'>>({})
  const [submitSuccess, setSubmitSuccess] = useState(false)

  // Refs
  const previewRequestIdRef = useRef(0)
  const previewAbortRef = useRef<AbortController | null>(null)
  const previewCacheRef = useRef<
    Map<string, { data: ChunkPreviewResponse; createdAt: number; durationMs: number }>
  >(new Map())
  const separatorSettingsLoadedRef = useRef(false)

  useEffect(() => {
    return () => {
      previewAbortRef.current?.abort()
    }
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') return
    const saved = (window.localStorage.getItem(STORAGE_DATASET_ID_KEY) || '').trim()
    if (saved) setDatasetIdState(saved)
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') return
    if (datasetId) window.localStorage.setItem(STORAGE_DATASET_ID_KEY, datasetId)
    else window.localStorage.removeItem(STORAGE_DATASET_ID_KEY)
  }, [datasetId])

  useEffect(() => {
    if (typeof window === 'undefined') return
    const raw = (window.localStorage.getItem(STORAGE_SEPARATOR_SETTINGS_KEY) || '').trim()
    if (!raw) {
      separatorSettingsLoadedRef.current = true
      return
    }
    try {
      const data = JSON.parse(raw) as any
      if (typeof data?.separatorPreset === 'string') setSeparatorPreset(data.separatorPreset)
      if (typeof data?.separatorCustom === 'string') setSeparatorCustom(data.separatorCustom)
      if (typeof data?.keepSeparator === 'boolean') setKeepSeparator(data.keepSeparator)
      if (typeof data?.separatorMaxChunkSize === 'number') setSeparatorMaxChunkSize(data.separatorMaxChunkSize)
    } catch {
      // ignore corrupted storage
    } finally {
      separatorSettingsLoadedRef.current = true
    }
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') return
    if (!separatorSettingsLoadedRef.current) return
    const payload = JSON.stringify({
      separatorPreset,
      separatorCustom,
      keepSeparator,
      separatorMaxChunkSize,
    })
    window.localStorage.setItem(STORAGE_SEPARATOR_SETTINGS_KEY, payload)
  }, [separatorPreset, separatorCustom, keepSeparator, separatorMaxChunkSize])

  // 当前文件
  const currentFileItem = fileList[currentFileIndex] || null
  const file = currentFileItem?.file || null

  // 初始化：从 parsedFiles 加载
  useEffect(() => {
    if (fileList.length === 0 && parsedFiles.length > 0) {
      const convertedFiles: ChunkPreviewFileItem[] = parsedFiles.map((pf) => {
        const content = pf.markdownContent || ''
        const originalFilename = pf.filename || 'document'

        const base = originalFilename.toLowerCase().endsWith('.md')
          ? originalFilename
          : originalFilename.replace(/\.[^/.]+$/, '')
        const internalFilename = originalFilename.toLowerCase().endsWith('.md') ? originalFilename : `${base}.md`

        const fileObj = new File([content], internalFilename, { type: 'text/markdown' })

        return {
          id: pf.id || makeId(),
          file: fileObj,
          displayName: originalFilename,
          originalFileType: pf.fileType,
          originalFileSize: pf.fileSize,
          addedAt: pf.parsedAt ? Date.parse(pf.parsedAt) : Date.now(),
        }
      })
      setFileList(convertedFiles)
    }
  }, [parsedFiles, fileList.length, makeId])

  // 同步 pipeline options
  useEffect(() => {
    if (typeof pipelineOptions.chunk_size === 'number' && pipelineOptions.chunk_size !== chunkSize) {
      setChunkSize(pipelineOptions.chunk_size)
    }
  }, [pipelineOptions.chunk_size, chunkSize])

  useEffect(() => {
    if (typeof pipelineOptions.chunk_overlap === 'number' && pipelineOptions.chunk_overlap !== chunkOverlap) {
      setChunkOverlap(pipelineOptions.chunk_overlap)
    }
  }, [pipelineOptions.chunk_overlap, chunkOverlap])

  useEffect(() => {
    if (!capabilities) return
    const available = parserBackendAvailable(parserBackend)
    if (available === false) {
      const fallback = capabilities.default_parser_backend || 'auto'
      if (fallback && fallback !== parserBackend) {
        setParserBackend(fallback)
        setError(`解析器不可用，已切换为 ${getParserLabel(fallback)}`)
      }
    }
  }, [capabilities, parserBackend, parserBackendAvailable, setParserBackend])

  useEffect(() => {
    if (!capabilities) return
    const available = chunkStrategyAvailable(chunkStrategy)
    if (available === false) {
      const fallback = capabilities.default_chunk_strategy || 'langchain_recursive'
      if (fallback && fallback !== chunkStrategy) {
        setChunkStrategy(fallback)
        setError(`切块策略不可用，已切换为 ${getChunkStrategyLabel(fallback)}`)
      }
    }
  }, [capabilities, chunkStrategy, chunkStrategyAvailable, setChunkStrategy])

  // Actions: 文件操作
  const addFiles = useCallback((files: File[]) => {
    setFileList((prev) => [
      ...prev,
      ...files.map((f) => ({
        id: makeId(),
        file: f,
        displayName: f.name,
        originalFileType: f.name.split('.').pop()?.toLowerCase(),
        originalFileSize: f.size,
        addedAt: Date.now(),
      })),
    ])
    setPreviewData(null)
    setError(null)
    setSubmitSuccess(false)
    setHoveredChunkIndex(null)
    setSelectedChunkIndex(null)
    setCreatedDocumentId(null)
  }, [makeId])

  const removeFile = useCallback((index: number) => {
    setFileList((prev) => {
      const newList = [...prev]
      newList.splice(index, 1)
      return newList
    })
    if (currentFileIndex >= index && currentFileIndex > 0) {
      setCurrentFileIndex((prev) => prev - 1)
    }
    setPreviewData(null)
    setHoveredChunkIndex(null)
    setSelectedChunkIndex(null)
    setCreatedDocumentId(null)
  }, [currentFileIndex])

  const clearFiles = useCallback(() => {
    previewAbortRef.current?.abort()
    previewAbortRef.current = null
    setFileList([])
    setCurrentFileIndex(0)
    setPreviewData(null)
    setError(null)
    setProcessedStatus({})
    setSubmitSuccess(false)
    setHoveredChunkIndex(null)
    setSelectedChunkIndex(null)
    setLastPreviewAt(null)
    setLastPreviewDurationMs(null)
    setCacheHit(false)
    setRunHistory([])
    previewCacheRef.current.clear()
    setCreatedDocumentId(null)
  }, [])

  const selectFile = useCallback((index: number) => {
    setCurrentFileIndex(index)
    setPreviewData(null)
    setError(null)
    setSubmitSuccess(false)
    setHoveredChunkIndex(null)
    setSelectedChunkIndex(null)
    setCreatedDocumentId(null)
  }, [])

  // Actions: 拖放
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault()
      setIsDragging(false)

      if (e.dataTransfer.items) {
        const files = await scanFiles(e.dataTransfer.items)
        if (files.length > 0) {
          addFiles(files)
        }
      } else if (e.dataTransfer.files.length > 0) {
        const files = Array.from(e.dataTransfer.files)
        addFiles(files)
      }
    },
    [addFiles]
  )

  // Actions: 使用示例
  const loadExample = useCallback(() => {
    const blob = new Blob([EXAMPLE_TEXT], { type: 'text/plain' })
    const exampleFile = new File([blob], 'rag-introduction.md', { type: 'text/markdown' })
    setFileList([
      {
        id: makeId(),
        file: exampleFile,
        displayName: exampleFile.name,
        originalFileType: 'md',
        originalFileSize: exampleFile.size,
        addedAt: Date.now(),
      },
    ])
    setCurrentFileIndex(0)
    setPreviewData(null)
    setError(null)
    setSubmitSuccess(false)
    setHoveredChunkIndex(null)
    setSelectedChunkIndex(null)
    setCreatedDocumentId(null)
  }, [makeId])

  const buildPreviewCacheKey = useCallback(() => {
    if (!file) return ''
    const pipelineKey = pipelineOverridesEnabled ? JSON.stringify(pipelineOptions || {}) : 'none'
    const separatorKey =
      chunkStrategy === 'separator'
        ? `sep:${separatorPreset}:${separatorCustom}:${keepSeparator ? 'keep' : 'drop'}:${separatorMaxChunkSize}`
        : 'sep:none'
    return [
      file.name,
      file.size,
      file.lastModified,
      datasetId || 'default-dataset',
      parserBackend,
      chunkStrategy,
      chunkSize,
      chunkOverlap,
      pipelineKey,
      separatorKey,
    ].join('::')
  }, [
    file,
    datasetId,
    parserBackend,
    chunkStrategy,
    chunkSize,
    chunkOverlap,
    pipelineOverridesEnabled,
    pipelineOptions,
    separatorPreset,
    separatorCustom,
    keepSeparator,
    separatorMaxChunkSize,
  ])

  const currentPreviewCacheKey = useMemo(() => buildPreviewCacheKey(), [buildPreviewCacheKey])
  const isPreviewDirty = Boolean(
    previewData && lastPreviewCacheKey && currentPreviewCacheKey && currentPreviewCacheKey !== lastPreviewCacheKey
  )

  // Actions: 执行预览
  const runPreview = useCallback(async (options?: { force?: boolean }) => {
    if (!file) return
    if (chunkOverlap >= chunkSize) {
      setError('重叠长度必须小于切块长度')
      return
    }
    const strategyAvailable = chunkStrategyAvailable(chunkStrategy)
    if (strategyAvailable === false) {
      setError(`当前切块策略不可用：${getChunkStrategyLabel(chunkStrategy)}`)
      return
    }

    const cacheKey = buildPreviewCacheKey()
    const cached = cacheKey ? previewCacheRef.current.get(cacheKey) : undefined
    if (cached && !options?.force) {
      setHoveredChunkIndex(null)
      setSelectedChunkIndex(null)
      setCreatedDocumentId(null)
      setPreviewData(cached.data)
      setLastPreviewAt(cached.createdAt)
      setLastPreviewDurationMs(cached.durationMs)
      setCacheHit(true)
      setLastPreviewCacheKey(cacheKey || null)
      setError(null)
      setRunHistory((prev) => [
        {
          id: makeId(),
          fileName: file.name,
          parserBackend,
          strategy: chunkStrategy,
          chunkSize,
          chunkOverlap,
          totalChunks: cached.data.total_chunks,
          durationMs: cached.durationMs,
          createdAt: Date.now(),
          cacheHit: true,
        },
        ...prev,
      ].slice(0, 20))
      return
    }

    const requestId = ++previewRequestIdRef.current
    previewAbortRef.current?.abort()
    const controller = new AbortController()
    previewAbortRef.current = controller
    setIsLoading(true)
    setError(null)
    setCacheHit(false)
    setHoveredChunkIndex(null)
    setSelectedChunkIndex(null)
    setCreatedDocumentId(null)
    const startTime = performance.now()

    try {
      const separator =
        chunkStrategy === 'separator'
          ? separatorPreset === 'custom'
            ? decodeSeparatorInput(separatorCustom) || '\n\n'
            : undefined
          : undefined

      const data = await documentApi.chunkPreview(file, {
        chunk_size: chunkSize,
        chunk_overlap: chunkOverlap,
        parser_backend: parserBackend,
        chunk_strategy: chunkStrategy,
        dataset_id: datasetId || undefined,
        pipeline: pipelineOverridesEnabled ? pipelineOptions : undefined,
        separator_preset: chunkStrategy === 'separator' ? separatorPreset : undefined,
        separator: separator,
        keep_separator: chunkStrategy === 'separator' ? keepSeparator : undefined,
        separator_max_chunk_size: chunkStrategy === 'separator' ? separatorMaxChunkSize : undefined,
      }, { signal: controller.signal })
      if (previewRequestIdRef.current !== requestId) return
      setPreviewData(data)
      const durationMs = Math.max(0, Math.round(performance.now() - startTime))
      const createdAt = Date.now()
      setLastPreviewAt(createdAt)
      setLastPreviewDurationMs(durationMs)
      if (cacheKey) {
        previewCacheRef.current.set(cacheKey, { data, createdAt, durationMs })
      }
      setLastPreviewCacheKey(cacheKey || null)
      setRunHistory((prev) => [
        {
          id: makeId(),
          fileName: file.name,
          parserBackend,
          strategy: chunkStrategy,
          chunkSize,
          chunkOverlap,
          totalChunks: data.total_chunks,
          durationMs,
          createdAt,
          cacheHit: false,
        },
        ...prev,
      ].slice(0, 20))
    } catch (err: any) {
      if (controller.signal.aborted) return
      if (previewRequestIdRef.current !== requestId) return
      setError(formatApiError(err, '预览失败'))
    } finally {
      if (previewAbortRef.current === controller) {
        previewAbortRef.current = null
      }
      if (previewRequestIdRef.current === requestId) {
        setIsLoading(false)
      }
    }
  }, [
    file,
    chunkSize,
    chunkOverlap,
    parserBackend,
    chunkStrategy,
    pipelineOverridesEnabled,
    pipelineOptions,
    chunkStrategyAvailable,
    buildPreviewCacheKey,
    makeId,
    datasetId,
    separatorPreset,
    separatorCustom,
    keepSeparator,
    separatorMaxChunkSize,
  ])

  const cancelPreview = useCallback(() => {
    previewAbortRef.current?.abort()
    previewAbortRef.current = null
    setIsLoading(false)
  }, [])

  // Actions: 提交入库
  const submitChunks = useCallback(async () => {
    if (!previewData || !file) return

    setIsSubmitting(true)
    setError(null)

    try {
      const chunks = previewData.chunks.map((chunk) => ({
        content: chunk.content,
        page_number: chunk.page_number,
        start_char: chunk.start_index,
        end_char: chunk.end_index,
        metadata: chunk.metadata,
      }))

      const pipeline = pipelineOverridesEnabled
        ? {
            ...pipelineOptions,
            chunk_size: chunkSize,
            chunk_overlap: chunkOverlap,
          }
        : undefined

      const separatorMeta =
        previewData.chunk_strategy === 'separator'
          ? {
              separator_preset: separatorPreset,
              separator_custom: separatorCustom,
              keep_separator: keepSeparator,
              separator_max_chunk_size: separatorMaxChunkSize,
            }
          : {}

      const created = await documentApi.createFromChunks({
        filename: previewData.filename,
        file_type: previewData.file_type,
        file_size: previewData.file_size,
        chunks,
        dataset_id: datasetId || undefined,
        metadata: {
          chunk_size: chunkSize,
          chunk_overlap: chunkOverlap,
          chunk_strategy: previewData.chunk_strategy,
          chunk_strategy_label: getChunkStrategyLabel(previewData.chunk_strategy),
          parser_backend: previewData.parser_backend,
          dataset_id: datasetId || undefined,
          ...separatorMeta,
        },
        pipeline,
      })

      setSubmitSuccess(true)
      setCreatedDocumentId(created?.id || null)
      setProcessedStatus((prev) => ({ ...prev, [currentFileItem?.id || file.name]: 'success' }))
      onConfirm?.({ chunk_size: chunkSize, chunk_overlap: chunkOverlap })
      toast.success('已成功入库')
    } catch (err: any) {
      setError(formatApiError(err, '入库失败'))
      setProcessedStatus((prev) => ({ ...prev, [currentFileItem?.id || file.name]: 'error' }))
    } finally {
      setIsSubmitting(false)
    }
  }, [
    previewData,
    file,
    currentFileItem,
    datasetId,
    chunkSize,
    chunkOverlap,
    pipelineOverridesEnabled,
    pipelineOptions,
    separatorPreset,
    separatorCustom,
    keepSeparator,
    separatorMaxChunkSize,
    onConfirm,
  ])

  // Actions: 更新配置
  const updateSettings = useCallback(
    (settings: Partial<Pick<ChunkPreviewState, 'chunkSize' | 'chunkOverlap' | 'strategy'>>) => {
      if (settings.chunkSize !== undefined) {
        setChunkSize(settings.chunkSize)
        updateOption('chunk_size', settings.chunkSize)
      }
      if (settings.chunkOverlap !== undefined) {
        setChunkOverlap(settings.chunkOverlap)
        updateOption('chunk_overlap', settings.chunkOverlap)
      }
      if (settings.strategy !== undefined) {
        setChunkStrategy(settings.strategy)
      }
    },
    [updateOption, setChunkStrategy]
  )

  const updateSeparatorSettings = useCallback(
    (
      settings: Partial<
        Pick<ChunkPreviewState, 'separatorPreset' | 'separatorCustom' | 'keepSeparator' | 'separatorMaxChunkSize'>
      >
    ) => {
      if (settings.separatorPreset !== undefined) setSeparatorPreset(settings.separatorPreset)
      if (settings.separatorCustom !== undefined) setSeparatorCustom(settings.separatorCustom)
      if (settings.keepSeparator !== undefined) setKeepSeparator(settings.keepSeparator)
      if (settings.separatorMaxChunkSize !== undefined) setSeparatorMaxChunkSize(settings.separatorMaxChunkSize)
    },
    []
  )

  // Actions: 重置
  const reset = useCallback(() => {
    setFileList([])
    setCurrentFileIndex(0)
    setPreviewData(null)
    setError(null)
    setProcessedStatus({})
    setSubmitSuccess(false)
    setHoveredChunkIndex(null)
    setSelectedChunkIndex(null)
    setLastPreviewAt(null)
    setLastPreviewDurationMs(null)
    setCacheHit(false)
    setRunHistory([])
    previewCacheRef.current.clear()
    setChunkSize(1000)
    setChunkOverlap(200)
    updateOption('chunk_size', 1000)
    updateOption('chunk_overlap', 200)
    setCreatedDocumentId(null)
    setShowOriginalPanel(true)
    setShowSettingsPanel(false)
    setSeparatorPreset('paragraph')
    setSeparatorCustom('\\n\\n')
    setKeepSeparator(true)
    setSeparatorMaxChunkSize(0)
  }, [updateOption])

  // 自动触发预览
  useEffect(() => {
    if (autoPreviewEnabled && file && !previewData && !isLoading && !isSubmitting && !error) {
      runPreview()
    }
  }, [autoPreviewEnabled, file, previewData, isLoading, isSubmitting, error, runPreview])

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const isCmdOrCtrl = event.metaKey || event.ctrlKey
      if (isCmdOrCtrl && event.key.toLowerCase() === 'enter') {
        event.preventDefault()
        runPreview({ force: true })
        return
      }
      if (isCmdOrCtrl && event.key.toLowerCase() === 's') {
        event.preventDefault()
        submitChunks()
        return
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [runPreview, submitChunks])

  const toggleAutoPreview = useCallback((enabled?: boolean) => {
    setAutoPreviewEnabled((prev) => (typeof enabled === 'boolean' ? enabled : !prev))
  }, [])

  const clearRunHistory = useCallback(() => {
    setRunHistory([])
  }, [])

  const toggleOriginalPanel = useCallback(() => {
    setShowOriginalPanel((prev) => !prev)
  }, [])

  const toggleSettingsPanel = useCallback(() => {
    setShowSettingsPanel((prev) => !prev)
  }, [])

  const setDatasetId = useCallback((value: string) => {
    setDatasetIdState((value || '').trim())
    setPreviewData(null)
    setError(null)
    setSubmitSuccess(false)
    setHoveredChunkIndex(null)
    setSelectedChunkIndex(null)
    setCreatedDocumentId(null)
  }, [])

  // 组装 Context Value
  const value: ChunkPreviewContextType = {
    // State
    fileList,
    currentFileIndex,
    isDragging,
    datasetId,
    isLoading,
    isSubmitting,
    showOriginalPanel,
    showSettingsPanel,
    error,
    createdDocumentId,
    previewData,
    hoveredChunkIndex,
    selectedChunkIndex,
    chunkSize,
    chunkOverlap,
    strategy: chunkStrategy,
    separatorPreset,
    separatorCustom,
    keepSeparator,
    separatorMaxChunkSize,
    lastPreviewAt,
    lastPreviewDurationMs,
    cacheHit,
    isPreviewDirty,
    autoPreviewEnabled,
    runHistory,

    // Derived
    currentFile: file,
    currentFileItem,
    submitSuccess,
    processedStatus,

    // Actions
    addFiles,
    removeFile,
    clearFiles,
    setCurrentFileIndex: selectFile,
    setDatasetId,
    setIsDragging,
    setHoveredChunkIndex,
    setSelectedChunkIndex,
    toggleOriginalPanel,
    toggleSettingsPanel,
    runPreview,
    cancelPreview,
    submitChunks,
    updateSettings,
    updateSeparatorSettings,
    reset,
    toggleAutoPreview,
    clearRunHistory,
    loadExample,
    handleDragOver,
    handleDragLeave,
    handleDrop,

    // External context
    parserBackend,
    setParserBackend,
    chunkStrategy,
    setChunkStrategy,
    onClose,
  }

  return <ChunkPreviewContext.Provider value={value}>{children}</ChunkPreviewContext.Provider>
}
