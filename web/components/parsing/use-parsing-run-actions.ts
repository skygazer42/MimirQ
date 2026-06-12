'use client'

import { useCallback, useEffect, type Dispatch, type SetStateAction } from 'react'
import { useTranslations } from 'next-intl'

import { toast } from 'sonner'

import { parsingApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { getParserLabel } from '@/lib/parser-options'
import { resolveParserBackendForFilename } from '@/lib/parser-compat'
import { restoreParsingRunFromMarkdown } from '@/lib/parsing-run-restore'
import { detachPromise } from '@/lib/utils'
import { type ParsedFileData } from '@/store/use-parsed-files-store'
import { type FileStatus } from '@/components/ui/file-queue-item'

import type { ParseFailureDiagnostics, ParsedFile } from './parsing-types'

type MutableRef<T> = {
  current: T
}

function estimateTableCount(markdownContent: string): number {
  const tableMatches = markdownContent.match(/\|.*\|/g) || []
  if (!tableMatches.length) return 0
  return (markdownContent.match(/^\|/gm) || []).length / 2
}

type UseParsingRunActionsOptions = {
  activeFile: ParsedFile | null
  autoParseFileId: string | null
  bumpParsingProgress: (prev: ParsedFile[], fileId: string) => ParsedFile[]
  cancelParse: (fileId: string) => void
  countMarkdownHeadings: (markdown: string) => number
  fileIdSetRef: MutableRef<Set<string>>
  filesRef: MutableRef<ParsedFile[]>
  imageCaptionEnabled: boolean
  imageOcrEnabled: boolean
  mapBackendStatusToLibraryStatus: (status?: string) => FileStatus
  parseControllersRef: MutableRef<Map<string, AbortController>>
  parseProgressIntervalsRef: MutableRef<Map<string, ReturnType<typeof setInterval>>>
  parserBackend: string
  setActiveBlockId: Dispatch<SetStateAction<string | null>>
  setAutoParseFileId: Dispatch<SetStateAction<string | null>>
  setFiles: Dispatch<SetStateAction<ParsedFile[]>>
  setHoveredBlockId: Dispatch<SetStateAction<string | null>>
  setRightPanelMode: Dispatch<SetStateAction<'blocks' | 'markdown'>>
  updateParsedFile: (id: string, updates: Partial<Omit<ParsedFileData, 'id'>>) => Promise<void>
  upsertParsedFile: (file: ParsedFileData) => void
  visibleQueueFiles: ParsedFile[]
  vlmCorrectionEnabled: boolean
}

function getMarkdownStats(markdownContent: string, apiStats: Record<string, unknown> | undefined, blockCount: number) {
  return {
    charCount: markdownContent.length,
    lineCount: markdownContent.split('\n').length,
    headingCount: 0,
    pageCount: typeof apiStats?.page_count === 'number' ? apiStats.page_count : undefined,
    tableCount:
      typeof apiStats?.table_count === 'number'
        ? apiStats.table_count
        : estimateTableCount(markdownContent),
    imageCount:
      typeof apiStats?.image_count === 'number'
        ? apiStats.image_count
        : (markdownContent.match(/!\[.*?\]\(.*?\)/g) || []).length,
    blockCount: typeof apiStats?.block_count === 'number' ? apiStats.block_count : blockCount,
  }
}

export function useParsingRunActions({
  activeFile,
  autoParseFileId,
  bumpParsingProgress,
  cancelParse,
  countMarkdownHeadings,
  fileIdSetRef,
  filesRef,
  imageCaptionEnabled,
  imageOcrEnabled,
  mapBackendStatusToLibraryStatus,
  parseControllersRef,
  parseProgressIntervalsRef,
  parserBackend,
  setActiveBlockId,
  setAutoParseFileId,
  setFiles,
  setHoveredBlockId,
  setRightPanelMode,
  updateParsedFile,
  upsertParsedFile,
  visibleQueueFiles,
  vlmCorrectionEnabled,
}: Readonly<UseParsingRunActionsOptions>) {
  const t = useTranslations('ParsingWorkbench')

  const parseFile = useCallback(
    async (fileId: string, backendOverride?: string) => {
      const file = filesRef.current.find((item) => item.id === fileId) || null
      if (!file) return
      if (file.librarySource === 'knowledge_base') {
        toast.warning(t('toasts.knowledgeBaseReadOnly'))
        return
      }

      cancelParse(fileId)
      const controller = new AbortController()
      parseControllersRef.current.set(fileId, controller)

      const resolvedRequested = resolveParserBackendForFilename(
        file.file.name,
        backendOverride || file.parserBackend || parserBackend
      )
      const requestedBackend = resolvedRequested.backend
      const requestedLabel = getParserLabel(requestedBackend)
      const startTime = Date.now()

      setFiles((prev) =>
        prev.map((item) =>
          item.id === fileId
            ? {
                ...item,
                status: 'parsing',
                error: undefined,
                progress: 0,
                parseStartTime: startTime,
                parserBackend: requestedBackend,
                parserLabel: requestedLabel,
                parseDiagnostics: undefined,
              }
            : item
        )
      )

      if (file.libraryId) {
        updateParsedFile(file.libraryId, {
          status: 'parsing',
          error: undefined,
          parser: requestedLabel,
          parserBackend: requestedBackend,
        })
      }

      const progressInterval = setInterval(() => {
        setFiles((prev) => bumpParsingProgress(prev, fileId))
      }, 300)
      parseProgressIntervalsRef.current.set(fileId, progressInterval)

      const clearProgressInterval = () => {
        clearInterval(progressInterval)
        if (parseProgressIntervalsRef.current.get(fileId) === progressInterval) {
          parseProgressIntervalsRef.current.delete(fileId)
        }
      }

      let libraryId = (file.libraryId || '').trim()

      try {
        if (!libraryId) {
          const created = await parsingApi.upload(file.file, {
            parser_backend: requestedBackend,
            dataset_id: file.datasetId,
          })
          libraryId = String(created.id || '').trim()
          if (!libraryId) throw new Error('Missing document id from backend')
          const createdMetadata = created.metadata
          const targetDatasetId =
            (typeof createdMetadata?.target_dataset_id === 'string' && createdMetadata.target_dataset_id.trim()) ||
            file.datasetId ||
            null
          const targetDatasetName =
            (typeof createdMetadata?.target_dataset_name === 'string' && createdMetadata.target_dataset_name.trim()) ||
            file.datasetName ||
            null

          upsertParsedFile({
            id: libraryId,
            filename: created.filename || file.file.name,
            fileType: created.file_type || file.file.name.split('.').pop()?.toLowerCase() || '',
            fileSize: Number(created.file_size || file.file.size),
            markdownContent: '',
            originalMarkdownContent: '',
            parsedAt: String(created.updated_at || created.created_at || new Date().toISOString()),
            parser: requestedLabel,
            parserBackend: requestedBackend,
            folderId: file.folderId,
            datasetId: targetDatasetId,
            datasetName: targetDatasetName,
            source: 'parsing_workspace',
            status: mapBackendStatusToLibraryStatus(created.status),
            error: created.error_message || undefined,
          })

          setFiles((prev) =>
            prev.map((item) =>
              item.id === fileId
                ? { ...item, libraryId, datasetId: targetDatasetId, datasetName: targetDatasetName }
                : item
            )
          )
        }

        if (controller.signal.aborted) return
        if (parseControllersRef.current.get(fileId) !== controller) return
        if (!fileIdSetRef.current.has(fileId)) return

        updateParsedFile(libraryId, {
          status: 'parsing',
          error: undefined,
          parser: requestedLabel,
          parserBackend: requestedBackend,
          folderId: file.folderId,
        })

        const data = await parsingApi.parse(libraryId, {
          parser_backend: requestedBackend,
          image_caption_enabled: imageCaptionEnabled,
          image_ocr_enabled: imageOcrEnabled,
          vlm_correction_enabled: vlmCorrectionEnabled,
          signal: controller.signal,
        })

        if (controller.signal.aborted) return
        if (parseControllersRef.current.get(fileId) !== controller) return
        if (!fileIdSetRef.current.has(fileId)) return

        clearProgressInterval()

        const rawMarkdown = (data.original_markdown_content || data.markdown_content || '').toString()
        const resolvedBackend = data.parser_backend || requestedBackend
        const resolvedLabel = getParserLabel(resolvedBackend)
        const fallbackDurationSec = Number.parseFloat(((Date.now() - startTime) / 1000).toFixed(1))
        const restored = restoreParsingRunFromMarkdown({
          rawMarkdown,
          cleanedMarkdown: (data.markdown_content || '').toString(),
        })
        const markdownContent = (restored?.cleanedMarkdown || data.markdown_content || '').toString()
        const blocks = restored?.blocks || []
        const durationSec = Number.isFinite(Number(data.parse_duration_sec))
          ? Number(data.parse_duration_sec)
          : fallbackDurationSec
        const runId = `${resolvedBackend}-${Date.now()}`
        const stats = getMarkdownStats(markdownContent, data.stats as Record<string, unknown> | undefined, blocks.length)
        stats.headingCount = countMarkdownHeadings(markdownContent)
        const responseExtras = data as unknown as { pdf_quality?: unknown; quality_gate?: unknown }

        const run = {
          id: runId,
          parserBackend: resolvedBackend,
          parserLabel: resolvedLabel,
          rawMarkdown,
          cleanedMarkdown: markdownContent,
          blocks,
          elements: data.elements || [],
          createdAt: Date.now(),
          pdfQuality: responseExtras.pdf_quality ?? null,
          qualityGate: responseExtras.quality_gate ?? null,
        }

        setFiles((prev) =>
          prev.map((item) =>
            item.id === fileId
              ? {
                  ...item,
                  status: 'parsed',
                  markdownContent,
                  parserBackend: resolvedBackend,
                  parserLabel: resolvedLabel,
                  parser: resolvedLabel,
                  progress: 100,
                  duration: durationSec,
                  stats,
                  elements: data.elements || [],
                  pdfQuality: responseExtras.pdf_quality ?? null,
                  qualityGate: responseExtras.quality_gate ?? null,
                  runs: [...(item.runs || []), run],
                  activeRunId: runId,
                }
              : item
          )
        )

        setActiveBlockId(null)
        setHoveredBlockId(null)
        setRightPanelMode(blocks.length ? 'blocks' : 'markdown')

        await updateParsedFile(libraryId, {
          filename: file.file.name,
          fileType: file.file.name.split('.').pop()?.toLowerCase() || '',
          fileSize: file.file.size,
          markdownContent,
          originalMarkdownContent: rawMarkdown,
          parser: resolvedLabel,
          parserBackend: resolvedBackend,
          durationSec,
          folderId: file.folderId,
          parsedAt: new Date().toISOString(),
          status: 'parsed',
          error: undefined,
        })
      } catch (err: unknown) {
        if (controller.signal.aborted) return
        if (parseControllersRef.current.get(fileId) !== controller) return
        if (!fileIdSetRef.current.has(fileId)) return

        const errorMessage = formatApiError(err, t('toasts.parseFailed'))
        const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
        const diagnostics: ParseFailureDiagnostics | undefined =
          detail && typeof detail === 'object' && !Array.isArray(detail)
            ? ((detail as { diagnostics?: ParseFailureDiagnostics }).diagnostics ?? undefined)
            : undefined

        setFiles((prev) =>
          prev.map((item) =>
            item.id === fileId
              ? {
                  ...item,
                  status: 'error',
                  error: errorMessage,
                  progress: 0,
                  parseDiagnostics: diagnostics,
                }
              : item
          )
        )

        if (libraryId) {
          updateParsedFile(libraryId, { status: 'error', error: errorMessage, parserBackend: requestedBackend })
        }
      } finally {
        if (parseControllersRef.current.get(fileId) === controller) {
          parseControllersRef.current.delete(fileId)
        }
        clearProgressInterval()
      }
    },
    [
      bumpParsingProgress,
      cancelParse,
      countMarkdownHeadings,
      fileIdSetRef,
      filesRef,
      imageCaptionEnabled,
      imageOcrEnabled,
      mapBackendStatusToLibraryStatus,
      parseControllersRef,
      parseProgressIntervalsRef,
      parserBackend,
      setActiveBlockId,
      setFiles,
      setHoveredBlockId,
      setRightPanelMode,
      t,
      updateParsedFile,
      upsertParsedFile,
      vlmCorrectionEnabled,
    ]
  )

  useEffect(() => {
    if (!autoParseFileId) return
    const id = autoParseFileId
    setAutoParseFileId(null)
    detachPromise(parseFile(id))
  }, [autoParseFileId, parseFile, setAutoParseFileId])

  const parseAllPending = useCallback(async () => {
    const targets = visibleQueueFiles.filter(
      (file) => file.librarySource !== 'knowledge_base' && (file.status === 'pending' || file.status === 'error')
    )
    for (const file of targets) {
      await parseFile(file.id)
    }
  }, [parseFile, visibleQueueFiles])

  const handleSelectRun = useCallback(
    (runId: string) => {
      if (!activeFile) return
      const nextRun = activeFile.runs?.find((run) => run.id === runId)
      if (!nextRun) return

      setFiles((prev) =>
        prev.map((file) =>
          file.id === activeFile.id
            ? {
                ...file,
                activeRunId: runId,
                markdownContent: nextRun.cleanedMarkdown,
                parserBackend: nextRun.parserBackend,
                parserLabel: nextRun.parserLabel,
              }
            : file
        )
      )

      setActiveBlockId(null)
      setHoveredBlockId(null)
      setRightPanelMode(nextRun.blocks.length ? 'blocks' : 'markdown')
    },
    [activeFile, setActiveBlockId, setFiles, setHoveredBlockId, setRightPanelMode]
  )

  return {
    handleSelectRun,
    parseAllPending,
    parseFile,
  }
}
