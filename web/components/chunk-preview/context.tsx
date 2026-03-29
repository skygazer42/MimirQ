/**
 * ChunkPreview Context
 * 管理切片预览的状态和业务逻辑
 */
'use client'

import { createContext, useContext, useState, useCallback, useRef, useEffect, useMemo, ReactNode } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { toast } from 'sonner'
import { documentApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { generateRequestId } from '@/lib/request-id'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { useParsedFiles } from '@/store/use-parsed-files-store'
import { getChunkStrategyLabel } from '@/lib/chunk-strategies'
import { getParserLabel } from '@/lib/parser-options'
import type { ChunkPreviewResponse, ManualChunk } from '@/types'
import type { ChunkOverride, ChunkOverrides, ChunkPreviewState, ChunkPreviewFileItem, ChunkPreviewContextType } from './types'
import { EXAMPLE_TEXT } from './constants'
import { scanFiles } from './utils/file-scanner'
import { getStoredOriginalPreviewMode, shouldRevealPdfPreviewOnChunkSelect } from './components/workbench/preview/pdf-dock'

const ChunkPreviewContext = createContext<ChunkPreviewContextType | null>(null)
const STORAGE_DATASET_ID_KEY = 'mimirq_chunk_preview_dataset_id'
const STORAGE_SEPARATOR_SETTINGS_KEY = 'mimirq_chunk_preview_separator_settings'
const STORAGE_FOCUS_FILE_ID_KEY = 'mimirq_chunk_preview_focus_file_id'
const STORAGE_PERF_SETTINGS_KEY = 'mimirq_chunk_preview_perf_settings'
const STORAGE_PARENT_CHILD_SETTINGS_KEY = 'mimirq_chunk_preview_parent_child_settings'

function decodeSeparatorInput(raw: string) {
  const value = (raw || '').trim()
  if (!value) return ''
  try {
    return JSON.parse(`"${value.replaceAll("\"", '\\"')}"`)
  } catch {
    return value
  }
}

function getApiErrorStatus(error: unknown): number | undefined {
  if (typeof error !== 'object' || error === null) return undefined
  const response = (error as { response?: { status?: unknown } }).response
  return typeof response?.status === 'number' ? response.status : undefined
}

function isChunkPreviewPdfFile(previewData: ChunkPreviewResponse | null, currentFile: File | null) {
  const fileType = String(previewData?.file_type || '').toLowerCase()
  if (fileType === 'pdf') return true
  const name = String(currentFile?.name || '').toLowerCase()
  return name.endsWith('.pdf')
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

export function ChunkPreviewProvider({ children, onConfirm, onClose }: Readonly<ChunkPreviewProviderProps>) {
  const router = useRouter()
  const searchParams = useSearchParams()
  // 外部依赖
  const parsedFiles = useParsedFiles((state) => state.files)
  const { parserBackend, setParserBackend } = useParserBackendPreference()
  const { chunkStrategy, setChunkStrategy } = useChunkStrategyPreference()
  const { enabled: pipelineOverridesEnabled, options: pipelineOptions, updateOption } = usePipelineOptions()
  const { capabilities, parserBackendAvailable, chunkStrategyAvailable } = usePipelineCapabilities()

  // 生成 ID 工具
  const makeId = useCallback(() => generateRequestId(), [])

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
  const [chunkOverrides, setChunkOverrides] = useState<ChunkOverrides>({})
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
    cacheKey?: string
  }>>([])

  const [chunkSize, setChunkSize] = useState(pipelineOptions.chunk_size ?? 1000)
  const [chunkOverlap, setChunkOverlap] = useState(pipelineOptions.chunk_overlap ?? 200)

  // Preview-only performance settings (payload guardrails; do not affect ingestion).
  const [includeOriginalText, setIncludeOriginalText] = useState(true)
  const [originalTextMaxChars, setOriginalTextMaxChars] = useState(100000)
  const [maxChunks, setMaxChunks] = useState(2000)
  const [useParseCache, setUseParseCache] = useState(true)

  const [separatorPreset, setSeparatorPreset] = useState('paragraph')
  const [separatorCustom, setSeparatorCustom] = useState('\\n\\n')
  const [keepSeparator, setKeepSeparator] = useState(true)
  const [separatorMaxChunkSize, setSeparatorMaxChunkSize] = useState(0)

  // Strategy-specific options (preview tuning).
  const [parentChildRatio, setParentChildRatio] = useState(0.5)
  const [parentChildMinChildSize, setParentChildMinChildSize] = useState(200)

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
  const parentChildSettingsLoadedRef = useRef(false)
  const focusFileLoadedRef = useRef(false)
  const deepLinkAppliedKeyRef = useRef<string>('')
  const lastSyncedChunkParamRef = useRef<string>('')

  useEffect(() => {
    return () => {
      previewAbortRef.current?.abort()
    }
  }, [])

  // Deep-link support: /chunk-preview?chunk=123 will auto-select chunk #123 (1-based)
  // once preview data is available.
  useEffect(() => {
    if (!previewData?.chunks?.length) return
    if (selectedChunkIndex != null) return

    const raw = (searchParams.get('chunk') || '').trim()
    if (!raw) return

    const n = Number.parseInt(raw, 10)
    if (!Number.isFinite(n)) return
    const idx = n - 1
    if (idx < 0 || idx >= previewData.chunks.length) return

    const key = `${previewData.filename}::${raw}`
    if (deepLinkAppliedKeyRef.current === key) return
    deepLinkAppliedKeyRef.current = key

    setSelectedChunkIndex(idx)
  }, [previewData?.chunks?.length, previewData?.filename, searchParams, selectedChunkIndex])

  useEffect(() => {
    if (
      !shouldRevealPdfPreviewOnChunkSelect({
        nextIndex: selectedChunkIndex,
        showOriginalPanel,
        isPdf: isChunkPreviewPdfFile(previewData, file),
        preferredPreviewMode: getStoredOriginalPreviewMode(),
      })
    ) {
      return
    }
    setShowOriginalPanel(true)
  }, [file, previewData, selectedChunkIndex, showOriginalPanel])

  // Sync selectedChunkIndex -> URL param (best-effort).
  // Important: avoid clobbering inbound deep links before we have applied them.
  useEffect(() => {
    if (globalThis.window === undefined) return

    const current = (searchParams.get('chunk') || '').trim()
    const next = selectedChunkIndex == null ? '' : String(selectedChunkIndex + 1)

    // Keep ref in sync when URL already matches state.
    if (current === next) {
      lastSyncedChunkParamRef.current = next
      return
    }

    // On initial load, `current` may come from a deep-link. Do not delete it just because
    // selection is still null (preview might not be ready yet).
    if (!next && current && current !== lastSyncedChunkParamRef.current) return

    const params = new URLSearchParams(searchParams.toString())
    if (next) params.set('chunk', next)
    else params.delete('chunk')

    lastSyncedChunkParamRef.current = next

    const qs = params.toString()
    const path = globalThis.window.location.pathname || '/chunk-preview'
    router.replace(`${path}${qs ? `?${qs}` : ''}`)
  }, [router, searchParams, selectedChunkIndex])

  useEffect(() => {
    if (globalThis.window === undefined) return
    const saved = (globalThis.window.localStorage.getItem(STORAGE_DATASET_ID_KEY) || '').trim()
    if (saved) setDatasetIdState(saved)
  }, [])

  useEffect(() => {
    if (globalThis.window === undefined) return
    if (datasetId) globalThis.window.localStorage.setItem(STORAGE_DATASET_ID_KEY, datasetId)
    else globalThis.window.localStorage.removeItem(STORAGE_DATASET_ID_KEY)
  }, [datasetId])

  useEffect(() => {
    if (globalThis.window === undefined) return
    const raw = (globalThis.window.localStorage.getItem(STORAGE_SEPARATOR_SETTINGS_KEY) || '').trim()
    if (!raw) {
      separatorSettingsLoadedRef.current = true
      return
    }
    try {
      const data = JSON.parse(raw)
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

  // Load parent-child strategy settings (best-effort).
  useEffect(() => {
    if (globalThis.window === undefined) return
    const raw = (globalThis.window.localStorage.getItem(STORAGE_PARENT_CHILD_SETTINGS_KEY) || '').trim()
    if (!raw) {
      parentChildSettingsLoadedRef.current = true
      return
    }
    try {
      const data = JSON.parse(raw)
      if (typeof data?.parentChildRatio === 'number' && Number.isFinite(data.parentChildRatio)) {
        setParentChildRatio(Math.max(0.05, Math.min(1.0, Number(data.parentChildRatio))))
      }
      if (typeof data?.parentChildMinChildSize === 'number' && Number.isFinite(data.parentChildMinChildSize)) {
        setParentChildMinChildSize(Math.max(50, Math.min(4000, Math.trunc(Number(data.parentChildMinChildSize)))))
      }
    } catch {
      // ignore corrupted storage
    } finally {
      parentChildSettingsLoadedRef.current = true
    }
  }, [])

  // Persist parent-child strategy settings.
  useEffect(() => {
    if (globalThis.window === undefined) return
    if (!parentChildSettingsLoadedRef.current) return
    const payload = JSON.stringify({
      parentChildRatio,
      parentChildMinChildSize,
    })
    globalThis.window.localStorage.setItem(STORAGE_PARENT_CHILD_SETTINGS_KEY, payload)
  }, [parentChildRatio, parentChildMinChildSize])

  useEffect(() => {
    if (globalThis.window === undefined) return
    if (!separatorSettingsLoadedRef.current) return
    const payload = JSON.stringify({
      separatorPreset,
      separatorCustom,
      keepSeparator,
      separatorMaxChunkSize,
    })
    globalThis.window.localStorage.setItem(STORAGE_SEPARATOR_SETTINGS_KEY, payload)
  }, [separatorPreset, separatorCustom, keepSeparator, separatorMaxChunkSize])

  // Load preview perf settings (best-effort).
  useEffect(() => {
    if (globalThis.window === undefined) return
    const raw = (globalThis.window.localStorage.getItem(STORAGE_PERF_SETTINGS_KEY) || '').trim()
    if (!raw) return
    try {
      const data = JSON.parse(raw)
      if (typeof data?.includeOriginalText === 'boolean') setIncludeOriginalText(data.includeOriginalText)
      if (typeof data?.originalTextMaxChars === 'number' && Number.isFinite(data.originalTextMaxChars)) {
        setOriginalTextMaxChars(Math.max(0, Math.min(2_000_000, Math.trunc(data.originalTextMaxChars))))
      }
      if (typeof data?.maxChunks === 'number' && Number.isFinite(data.maxChunks)) {
        setMaxChunks(Math.max(0, Math.min(20000, Math.trunc(data.maxChunks))))
      }
      if (typeof data?.useParseCache === 'boolean') setUseParseCache(Boolean(data.useParseCache))
    } catch {
      // ignore corrupted storage
    }
  }, [])

  // Persist preview perf settings.
  useEffect(() => {
    if (globalThis.window === undefined) return
    const payload = JSON.stringify({
      includeOriginalText,
      originalTextMaxChars,
      maxChunks,
      useParseCache,
    })
    globalThis.window.localStorage.setItem(STORAGE_PERF_SETTINGS_KEY, payload)
  }, [includeOriginalText, originalTextMaxChars, maxChunks, useParseCache])

  // 当前文件
  const currentFileItem = fileList[currentFileIndex] || null
  const file = currentFileItem?.file || null

  // Keep currentFileIndex valid when fileList changes.
  useEffect(() => {
    if (fileList.length === 0) {
      setCurrentFileIndex(0)
      focusFileLoadedRef.current = false
      if (globalThis.window !== undefined) {
        globalThis.window.localStorage.removeItem(STORAGE_FOCUS_FILE_ID_KEY)
      }
      return
    }
    if (currentFileIndex >= fileList.length) {
      setCurrentFileIndex(fileList.length - 1)
    }
  }, [currentFileIndex, fileList.length])

  // Persist the currently focused file (best-effort UX when coming back to the page).
  useEffect(() => {
    if (globalThis.window === undefined) return
    if (!currentFileItem?.id) return
    globalThis.window.localStorage.setItem(STORAGE_FOCUS_FILE_ID_KEY, currentFileItem.id)
  }, [currentFileItem?.id])

  // Restore focused file after fileList is initialized.
  useEffect(() => {
    if (globalThis.window === undefined) return
    if (focusFileLoadedRef.current) return
    if (fileList.length === 0) return
    const saved = (globalThis.window.localStorage.getItem(STORAGE_FOCUS_FILE_ID_KEY) || '').trim()
    if (saved) {
      const idx = fileList.findIndex((f) => f.id === saved)
      if (idx >= 0) setCurrentFileIndex(idx)
    }
    focusFileLoadedRef.current = true
  }, [fileList])

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

  // Keep overlap consistent for separator strategy (no overlap).
  useEffect(() => {
    if (chunkStrategy !== 'separator') return
    if (chunkOverlap === 0) return
    setChunkOverlap(0)
    updateOption('chunk_overlap', 0)
  }, [chunkOverlap, chunkStrategy, updateOption])

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
    setChunkOverrides({})
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
    setChunkOverrides({})
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
    setChunkOverrides({})
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
    setChunkOverrides({})
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
    const parentChildKey =
      chunkStrategy === 'parent_child'
        ? `pc:${parentChildRatio}:${parentChildMinChildSize}`
        : 'pc:none'
    const perfKey = `perf:${includeOriginalText ? 'orig' : 'noorig'}:${originalTextMaxChars}:${maxChunks}:${useParseCache ? 'pcache' : 'nopcache'}`
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
      parentChildKey,
      perfKey,
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
    parentChildRatio,
    parentChildMinChildSize,
    includeOriginalText,
    originalTextMaxChars,
    maxChunks,
    useParseCache,
  ])

  const currentPreviewCacheKey = useMemo(() => buildPreviewCacheKey(), [buildPreviewCacheKey])
  const isPreviewDirty = Boolean(
    previewData && lastPreviewCacheKey && currentPreviewCacheKey && currentPreviewCacheKey !== lastPreviewCacheKey
  )

  // Actions: 执行预览
  const runPreview = useCallback(async (options?: { force?: boolean }) => {
    if (!file) return
    const effectiveOverlap = chunkStrategy === 'separator' ? 0 : chunkOverlap
    if (effectiveOverlap >= chunkSize) {
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
      setChunkOverrides({})
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
          chunkOverlap: effectiveOverlap,
          totalChunks: cached.data.total_chunks,
          durationMs: cached.durationMs,
          createdAt: Date.now(),
          cacheHit: true,
          cacheKey: cacheKey || undefined,
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
        (() => {
    if (chunkStrategy === 'separator') {
        if (separatorPreset === 'custom') {
            return decodeSeparatorInput(separatorCustom) || '\n\n';
        }
        else {
            return undefined;
        }
    }
    else {
        return undefined;
    }
})()

      const baseParams = {
    chunk_size: chunkSize,
    chunk_overlap: effectiveOverlap,
    include_original_text: includeOriginalText,
    original_text_max_chars: originalTextMaxChars,
    max_chunks: maxChunks,
    use_parse_cache: useParseCache,
    parser_backend: parserBackend,
    chunk_strategy: chunkStrategy,
    child_ratio: chunkStrategy === 'parent_child' ? parentChildRatio : undefined,
    min_child_size: chunkStrategy === 'parent_child' ? parentChildMinChildSize : undefined,
    dataset_id: datasetId || undefined,
    pipeline: pipelineOverridesEnabled ? pipelineOptions : undefined,
    separator_preset: chunkStrategy === 'separator' ? separatorPreset : undefined,
    separator: separator,
    keep_separator: chunkStrategy === 'separator' ? keepSeparator : undefined,
    separator_max_chunk_size: chunkStrategy === 'separator' ? separatorMaxChunkSize : undefined,
}

      // Enterprise UX: when parse cache is enabled and we have a prior file_sha256, avoid re-uploading the file.
      // If server cache miss/disabled, fall back to uploading.
      let data: ChunkPreviewResponse
      const sha = previewData?.file_sha256
      const fileType = previewData?.file_type
      if (useParseCache && sha && (fileType || file.name)) {
        try {
          data = await documentApi.chunkPreviewBySha(
            {
              file_sha256: sha,
              file_type: fileType || undefined,
              filename: file.name,
              file_size: file.size,
             ...baseParams,
            },
            { signal: controller.signal }
          )
        } catch (err: unknown) {
          const status = getApiErrorStatus(err)
          if (status === 400 || status === 404) {
            data = await documentApi.chunkPreview(file, baseParams, { signal: controller.signal })
          } else {
            throw err
          }
        }
      } else {
        data = await documentApi.chunkPreview(file, baseParams, { signal: controller.signal })
      }
      if (previewRequestIdRef.current !== requestId) return
      setChunkOverrides({})
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
          chunkOverlap: effectiveOverlap,
          totalChunks: data.total_chunks,
          durationMs,
          createdAt,
          cacheHit: false,
          cacheKey: cacheKey || undefined,
        },
        ...prev,
      ].slice(0, 20))
    } catch (err: unknown) {
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
    includeOriginalText,
    originalTextMaxChars,
    maxChunks,
    useParseCache,
    parentChildRatio,
    parentChildMinChildSize,
    previewData,
  ])

  const cancelPreview = useCallback(() => {
    previewAbortRef.current?.abort()
    previewAbortRef.current = null
    setIsLoading(false)
  }, [])

  const getCachedPreview = useCallback((cacheKey: string) => {
    const key = (cacheKey || '').trim()
    if (!key) return null
    return previewCacheRef.current.get(key)?.data ?? null
  }, [])

  // Actions: 提交入库
  const submitChunks = useCallback(async () => {
    if (!previewData || !file) return

    setIsSubmitting(true)
    setError(null)

    try {
      const chunks = previewData.chunks.reduce<ManualChunk[]>((acc, chunk) => {
        const idx = typeof chunk.index === 'number' ? chunk.index : previewData.chunks.indexOf(chunk)
        const override = chunkOverrides[idx] || null
        if (override?.disabled) return acc
        const content = String(override?.content ?? chunk.content ?? '')
        const metadata = (override?.metadata ?? chunk.metadata ?? {})
        acc.push({
          content,
          page_number: chunk.page_number,
          start_char: chunk.start_index,
          end_char: chunk.end_index,
          metadata,
        })
        return acc
      }, [])

      if (!chunks.length) {
        setError('No chunks to submit (all skipped)')
        toast.error('No chunks to submit (all skipped)')
        return
      }

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
    } catch (err: unknown) {
      setError(formatApiError(err, '入库失败'))
      setProcessedStatus((prev) => ({ ...prev, [currentFileItem?.id || file.name]: 'error' }))
    } finally {
      setIsSubmitting(false)
    }
  }, [
    previewData,
    chunkOverrides,
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
  const updateChunkOverride = useCallback(
    (index: number, override: ChunkOverride) => {
      const idx = Math.trunc(Number(index))
      if (!Number.isFinite(idx) || idx < 0) return
      setChunkOverrides((prev) => {
        const next = { ...prev }
        const cur = next[idx] || {}
        next[idx] = { ...cur, ...override, updatedAt: Date.now() }
        return next
      })
    },
    []
  )

  const toggleChunkDisabled = useCallback((index: number) => {
    const idx = Math.trunc(Number(index))
    if (!Number.isFinite(idx) || idx < 0) return

    setChunkOverrides((prev) => {
      const next = { ...prev }
      const cur = next[idx] || {}
      const nextDisabled = !Boolean(cur.disabled)

      if (nextDisabled) {
        next[idx] = { ...cur, disabled: true, updatedAt: Date.now() }
        return next
      }

      const { disabled: _omit, ...rest } = cur
      const hasOther = rest.content !== undefined || rest.metadata !== undefined
      if (!hasOther) {
        delete next[idx]
        return next
      }

      next[idx] = { ...rest, updatedAt: Date.now() }
      return next
    })
  }, [])

  const setChunksDisabled = useCallback((indices: number[], disabled: boolean) => {
    const list = Array.from(new Set((indices || []).map((n) => Math.trunc(Number(n))).filter((n) => Number.isFinite(n) && n >= 0)))
    if (list.length === 0) return

    setChunkOverrides((prev) => {
      const now = Date.now()
      const next = { ...prev }
      let changed = false

      for (const idx of list) {
        const cur = next[idx] || {}
        const curDisabled = Boolean(cur.disabled)

        if (disabled) {
          if (curDisabled) continue
          next[idx] = { ...cur, disabled: true, updatedAt: now }
          changed = true
          continue
        }

        if (!curDisabled) continue
        const { disabled: _omit, ...rest } = cur
        const hasOther = rest.content !== undefined || rest.metadata !== undefined
        if (hasOther) {
          next[idx] = { ...rest, updatedAt: now }
        } else {
          delete next[idx]
        }
        changed = true
      }

      return changed ? next : prev
    })
  }, [])

  const clearChunkOverride = useCallback((index: number) => {
    const idx = Math.trunc(Number(index))
    if (!Number.isFinite(idx) || idx < 0) return
    setChunkOverrides((prev) => {
      if (!(idx in prev)) return prev
      const next = { ...prev }
      delete next[idx]
      return next
    })
  }, [])

  const clearAllChunkOverrides = useCallback(() => {
    setChunkOverrides({})
  }, [])

  const updateSettings = useCallback(
    (settings: Partial<Pick<ChunkPreviewState, 'chunkSize' | 'chunkOverlap' | 'strategy'>>) => {
      const nextStrategy = settings.strategy === undefined ? chunkStrategy : settings.strategy

      if (settings.chunkSize !== undefined) {
        setChunkSize(settings.chunkSize)
        updateOption('chunk_size', settings.chunkSize)
      }
      if (settings.chunkOverlap !== undefined) {
        const nextOverlap = nextStrategy === 'separator' ? 0 : settings.chunkOverlap
        setChunkOverlap(nextOverlap)
        updateOption('chunk_overlap', nextOverlap)
      }
      if (settings.strategy !== undefined) {
        setChunkStrategy(settings.strategy)
        if (settings.strategy === 'separator') {
          // separator does not use overlap; keep state consistent so validation/API stay clean.
          setChunkOverlap(0)
          updateOption('chunk_overlap', 0)
        }
      }
    },
    [chunkStrategy, updateOption, setChunkStrategy]
  )

  const updatePerfSettings = useCallback(
    (
      settings: Partial<Pick<ChunkPreviewState, 'includeOriginalText' | 'originalTextMaxChars' | 'maxChunks' | 'useParseCache'>>
    ) => {
      if (settings.includeOriginalText !== undefined) setIncludeOriginalText(Boolean(settings.includeOriginalText))
      if (settings.originalTextMaxChars !== undefined) {
        const n = Number(settings.originalTextMaxChars)
        if (Number.isFinite(n)) setOriginalTextMaxChars(Math.max(0, Math.min(2_000_000, Math.trunc(n))))
      }
      if (settings.maxChunks !== undefined) {
        const n = Number(settings.maxChunks)
        if (Number.isFinite(n)) setMaxChunks(Math.max(0, Math.min(20000, Math.trunc(n))))
      }
      if (settings.useParseCache !== undefined) setUseParseCache(Boolean(settings.useParseCache))
    },
    []
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
  const updateParentChildSettings = useCallback(
    (settings: Partial<Pick<ChunkPreviewState, 'parentChildRatio' | 'parentChildMinChildSize'>>) => {
      if (settings.parentChildRatio !== undefined) {
        const n = Number(settings.parentChildRatio)
        if (Number.isFinite(n)) setParentChildRatio(Math.max(0.05, Math.min(1.0, n)))
      }
      if (settings.parentChildMinChildSize !== undefined) {
        const n = Number(settings.parentChildMinChildSize)
        if (Number.isFinite(n)) setParentChildMinChildSize(Math.max(50, Math.min(4000, Math.trunc(n))))
      }
    },
    []
  )

  const reset = useCallback(() => {
    setFileList([])
    setCurrentFileIndex(0)
    setPreviewData(null)
    setChunkOverrides({})
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
    setIncludeOriginalText(true)
    setOriginalTextMaxChars(100000)
    setMaxChunks(2000)
    setUseParseCache(true)
    updateOption('chunk_size', 1000)
    updateOption('chunk_overlap', 200)
    setCreatedDocumentId(null)
    setShowOriginalPanel(true)
    setShowSettingsPanel(false)
    setSeparatorPreset('paragraph')
    setSeparatorCustom('\\n\\n')
    setKeepSeparator(true)
    setSeparatorMaxChunkSize(0)
    setParentChildRatio(0.5)
    setParentChildMinChildSize(200)
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
    globalThis.window.addEventListener('keydown', handleKeyDown)
    return () => globalThis.window.removeEventListener('keydown', handleKeyDown)
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

  const setOriginalPanelVisible = useCallback((visible: boolean) => {
    setShowOriginalPanel(visible)
  }, [])

  const toggleSettingsPanel = useCallback(() => {
    setShowSettingsPanel((prev) => !prev)
  }, [])

  const setDatasetId = useCallback((value: string) => {
    setDatasetIdState((value || '').trim())
    setPreviewData(null)
    setChunkOverrides({})
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
    chunkOverrides,
    hoveredChunkIndex,
    selectedChunkIndex,
    chunkSize,
    chunkOverlap,
    includeOriginalText,
    originalTextMaxChars,
    maxChunks,
    useParseCache,
    strategy: chunkStrategy,
    separatorPreset,
    separatorCustom,
    keepSeparator,
    separatorMaxChunkSize,
    parentChildRatio,
    parentChildMinChildSize,
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
    updateChunkOverride,
    toggleChunkDisabled,
    setChunksDisabled,
    clearChunkOverride,
    clearAllChunkOverrides,
    toggleOriginalPanel,
    setOriginalPanelVisible,
    toggleSettingsPanel,
    runPreview,
    cancelPreview,
    submitChunks,
    updateSettings,
    updatePerfSettings,
    updateSeparatorSettings,
    updateParentChildSettings,
    reset,
    toggleAutoPreview,
    clearRunHistory,
    getCachedPreview,
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
