/**
 * ChunkPreview Context
 * 管理切片预览的状态和业务逻辑
 */
'use client'

import { createContext, useContext, useState, useCallback, useRef, useEffect, ReactNode } from 'react'
import { documentApi } from '@/lib/api-client'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { useParsedFiles } from '@/store/use-parsed-files-store'
import { getChunkStrategyLabel } from '@/lib/chunk-strategies'
import type { ChunkPreviewResponse } from '@/types'
import type { ChunkPreviewState, ChunkPreviewActions, ChunkPreviewFileItem, ChunkPreviewContextType } from './types'
import { EXAMPLE_TEXT } from './constants'
import { scanFiles } from './utils/file-scanner'

const ChunkPreviewContext = createContext<ChunkPreviewContextType | null>(null)

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
  const { files: parsedFiles } = useParsedFiles()
  const { parserBackend, setParserBackend } = useParserBackendPreference()
  const { chunkStrategy, setChunkStrategy } = useChunkStrategyPreference()
  const { enabled: pipelineOverridesEnabled, options: pipelineOptions, updateOption } = usePipelineOptions()

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
  const [error, setError] = useState<string | null>(null)

  const [previewData, setPreviewData] = useState<ChunkPreviewResponse | null>(null)
  const [hoveredChunkIndex, setHoveredChunkIndex] = useState<number | null>(null)

  const [chunkSize, setChunkSize] = useState(pipelineOptions.chunk_size ?? 1000)
  const [chunkOverlap, setChunkOverlap] = useState(pipelineOptions.chunk_overlap ?? 200)

  // 其他状态
  const [processedStatus, setProcessedStatus] = useState<Record<string, 'pending' | 'success' | 'error'>>({})
  const [submitSuccess, setSubmitSuccess] = useState(false)

  // Refs
  const previewRequestIdRef = useRef(0)

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
      })),
    ])
    setPreviewData(null)
    setError(null)
    setSubmitSuccess(false)
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
  }, [currentFileIndex])

  const selectFile = useCallback((index: number) => {
    setCurrentFileIndex(index)
    setPreviewData(null)
    setError(null)
    setSubmitSuccess(false)
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
  const useExample = useCallback(() => {
    const blob = new Blob([EXAMPLE_TEXT], { type: 'text/plain' })
    const exampleFile = new File([blob], 'rag-introduction.md', { type: 'text/markdown' })
    setFileList([
      {
        id: makeId(),
        file: exampleFile,
        displayName: exampleFile.name,
        originalFileType: 'md',
        originalFileSize: exampleFile.size,
      },
    ])
    setCurrentFileIndex(0)
    setPreviewData(null)
    setError(null)
    setSubmitSuccess(false)
  }, [makeId])

  // Actions: 执行预览
  const runPreview = useCallback(async () => {
    if (!file) return

    const requestId = ++previewRequestIdRef.current
    setIsLoading(true)
    setError(null)

    try {
      const data = await documentApi.chunkPreview(file, {
        chunk_size: chunkSize,
        chunk_overlap: chunkOverlap,
        parser_backend: parserBackend,
        chunk_strategy: chunkStrategy,
        pipeline: pipelineOverridesEnabled ? pipelineOptions : undefined,
      })
      if (previewRequestIdRef.current !== requestId) return
      setPreviewData(data)
    } catch (err: any) {
      if (previewRequestIdRef.current !== requestId) return
      setError(err.response?.data?.detail || err.response?.data?.message || err.message || '预览失败')
    } finally {
      if (previewRequestIdRef.current === requestId) {
        setIsLoading(false)
      }
    }
  }, [file, chunkSize, chunkOverlap, parserBackend, chunkStrategy, pipelineOverridesEnabled, pipelineOptions])

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
            governance_enabled: pipelineOptions.governance_enabled,
            governance_remove_toc_lines: pipelineOptions.governance_remove_toc_lines,
            governance_remove_noise_lines: pipelineOptions.governance_remove_noise_lines,
            governance_unwrap_lines: pipelineOptions.governance_unwrap_lines,
            governance_remove_common_lines: pipelineOptions.governance_remove_common_lines,
            governance_unwrap_max_line_length: pipelineOptions.governance_unwrap_max_line_length,
            governance_noise_min_chars: pipelineOptions.governance_noise_min_chars,
            governance_noise_ratio_threshold: pipelineOptions.governance_noise_ratio_threshold,
            governance_common_lines_min_docs: pipelineOptions.governance_common_lines_min_docs,
            governance_common_lines_min_ratio: pipelineOptions.governance_common_lines_min_ratio,
            chunk_size: chunkSize,
            chunk_overlap: chunkOverlap,
            chunk_vector_enabled: pipelineOptions.chunk_vector_enabled,
            bm25_index_enabled: pipelineOptions.bm25_index_enabled,
            kg_enabled: pipelineOptions.kg_enabled,
            event_vector_enabled: pipelineOptions.event_vector_enabled,
            entity_vector_enabled: pipelineOptions.entity_vector_enabled,
          }
        : undefined

      await documentApi.createFromChunks({
        filename: previewData.filename,
        file_type: previewData.file_type,
        file_size: previewData.file_size,
        chunks,
        metadata: {
          chunk_size: chunkSize,
          chunk_overlap: chunkOverlap,
          chunk_strategy: previewData.chunk_strategy,
          chunk_strategy_label: getChunkStrategyLabel(previewData.chunk_strategy),
          parser_backend: previewData.parser_backend,
        },
        pipeline,
      })

      setSubmitSuccess(true)
      setProcessedStatus((prev) => ({ ...prev, [currentFileItem?.id || file.name]: 'success' }))
      onConfirm?.({ chunk_size: chunkSize, chunk_overlap: chunkOverlap })
    } catch (err: any) {
      setError(err.response?.data?.detail || err.response?.data?.message || err.message || '入库失败')
      setProcessedStatus((prev) => ({ ...prev, [currentFileItem?.id || file.name]: 'error' }))
    } finally {
      setIsSubmitting(false)
    }
  }, [previewData, file, currentFileItem, chunkSize, chunkOverlap, pipelineOverridesEnabled, pipelineOptions, onConfirm])

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

  // Actions: 重置
  const reset = useCallback(() => {
    setFileList([])
    setCurrentFileIndex(0)
    setPreviewData(null)
    setError(null)
    setProcessedStatus({})
    setSubmitSuccess(false)
    setChunkSize(1000)
    setChunkOverlap(200)
    updateOption('chunk_size', 1000)
    updateOption('chunk_overlap', 200)
  }, [updateOption])

  // 自动触发预览
  useEffect(() => {
    if (file && !previewData && !isLoading && !isSubmitting && !error) {
      runPreview()
    }
  }, [file, previewData, isLoading, isSubmitting, error, runPreview])

  // 组装 Context Value
  const value: ChunkPreviewContextType = {
    // State
    fileList,
    currentFileIndex,
    isDragging,
    isLoading,
    isSubmitting,
    error,
    previewData,
    hoveredChunkIndex,
    chunkSize,
    chunkOverlap,
    strategy: chunkStrategy,

    // Derived
    currentFile: file,
    currentFileItem,
    submitSuccess,
    processedStatus,

    // Actions
    addFiles,
    removeFile,
    setCurrentFileIndex: selectFile,
    setIsDragging,
    setHoveredChunkIndex,
    runPreview,
    submitChunks,
    updateSettings,
    reset,
    useExample,
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
