'use client'

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  type Dispatch,
  type RefObject,
  type SetStateAction,
} from 'react'
import { useTranslations } from 'next-intl'
import { useQueryClient } from '@tanstack/react-query'
import { z } from 'zod'

import { toast } from 'sonner'

import { parsingApi } from '@/lib/api/parsing'
import { documentApi } from '@/lib/api/documents'
import { formatApiError } from '@/lib/api-errors'
import { reportClientWarning } from '@/lib/client-logging'
import { saveDocSourceToCache } from '@/lib/doc-content-cache'
import { getAuthCacheScope, getAuthSessionRevision } from '@/lib/auth-storage'
import { getParserLabel } from '@/lib/parser-options'
import { resolveParserBackendForFilename } from '@/lib/parser-compat'
import { restoreParsingRunFromMarkdown } from '@/lib/parsing-run-restore'
import { generateRequestId } from '@/lib/request-id'
import { useParsedFiles, type ParsedFileData } from '@/store/use-parsed-files-store'

import { parseFailureDiagnosticsSchema, type ParsedFile } from './parsing-types'
import {
  bumpParsingProgress,
  buildParsingStatistics,
  mapBackendStatusToLibraryStatus,
  normalizeParsingBackendCandidate,
} from './parsing-page-utils'

const parsingFailureSchema = z.object({
  response: z.object({
    data: z.object({
      detail: z.object({ diagnostics: parseFailureDiagnosticsSchema }),
    }),
  }),
})

type UseParsingRunActionsOptions = {
  activeFile: ParsedFile | null
  autoParseFileId: string | null
  cancelParse: (fileId: string) => void
  filesRef: RefObject<ParsedFile[]>
  imageCaptionEnabled: boolean
  imageOcrEnabled: boolean
  parseControllersRef: RefObject<Map<string, AbortController>>
  parseProgressIntervalsRef: RefObject<Map<string, ReturnType<typeof setInterval>>>
  replaceParsedFile: (id: string, file: ParsedFileData) => void
  removeParsedFile: (id: string) => void
  restoreLibraryFileFromCache: (libraryId: string, autoParse: boolean) => Promise<void>
  setActiveBlockId: Dispatch<SetStateAction<string | null>>
  setActiveLibraryFileId: Dispatch<SetStateAction<string | null>>
  setAutoParseFileId: Dispatch<SetStateAction<string | null>>
  setFiles: Dispatch<SetStateAction<ParsedFile[]>>
  setHoveredBlockId: Dispatch<SetStateAction<string | null>>
  setRightPanelMode: Dispatch<SetStateAction<'blocks' | 'markdown'>>
  setSelectedGovernanceFileIds: Dispatch<SetStateAction<Set<string>>>
  updateParsedFile: (id: string, updates: Partial<Omit<ParsedFileData, 'id'>>) => Promise<void>
  upsertParsedFile: (file: ParsedFileData) => void
  visibleQueueFiles: ParsedFile[]
  vlmCorrectionEnabled: boolean
}

export function useParsingRunActions({
  activeFile,
  autoParseFileId,
  cancelParse,
  filesRef,
  imageCaptionEnabled,
  imageOcrEnabled,
  parseControllersRef,
  parseProgressIntervalsRef,
  replaceParsedFile,
  removeParsedFile,
  restoreLibraryFileFromCache,
  setActiveBlockId,
  setActiveLibraryFileId,
  setAutoParseFileId,
  setFiles,
  setHoveredBlockId,
  setRightPanelMode,
  setSelectedGovernanceFileIds,
  updateParsedFile,
  upsertParsedFile,
  visibleQueueFiles,
  vlmCorrectionEnabled,
}: Readonly<UseParsingRunActionsOptions>) {
  const t = useTranslations('ParsingWorkbench')
  const queryClient = useQueryClient()
  const activeFileIdRef = useRef(activeFile?.id)
  const batchParseRef = useRef<AbortController | null>(null)
  useLayoutEffect(
    () => () => {
      batchParseRef.current?.abort()
    },
    [],
  )
  useEffect(() => {
    activeFileIdRef.current = activeFile?.id
  }, [activeFile?.id])

  const parseFile = useCallback(
    async (requestedFileId: string, backendOverride?: string) => {
      const file = filesRef.current.find((item) => item.id === requestedFileId || item.libraryId === requestedFileId)
      if (file === undefined) {
        const libraryFile = useParsedFiles.getState().files.find((item) => item.id === requestedFileId)
        if (libraryFile === undefined) return
        if (libraryFile.source === 'knowledge_base') toast.warning(t('toasts.knowledgeBaseReadOnly'))
        else await restoreLibraryFileFromCache(requestedFileId, true)
        return
      }
      const fileId = file.id
      if (file.librarySource === 'knowledge_base') {
        toast.warning(t('toasts.knowledgeBaseReadOnly'))
        return
      }

      cancelParse(fileId)
      const controller = new AbortController()
      parseControllersRef.current.set(fileId, controller)
      const scope = getAuthCacheScope()
      const revision = getAuthSessionRevision()
      const isCurrent = () =>
        !controller.signal.aborted &&
        parseControllersRef.current.get(fileId) === controller &&
        filesRef.current.some((item) => item.id === fileId) &&
        scope === getAuthCacheScope() &&
        revision === getAuthSessionRevision()

      const resolvedRequested = resolveParserBackendForFilename(file.name, backendOverride ?? file.parserBackend)
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
            : item,
        ),
      )

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

      const localLibraryId = file.librarySource === undefined ? file.libraryId : undefined
      let libraryId = file.libraryId
      let replacement: { originalId: string; document: Awaited<ReturnType<typeof parsingApi.upload>> } | undefined

      try {
        const loadError = useParsedFiles.getState().loadError
        if (loadError !== undefined) throw loadError
        if (libraryId === undefined || localLibraryId !== undefined) {
          const created = await parsingApi.upload(file.file, {
            parser_backend: requestedBackend,
            dataset_id: file.datasetId,
          })
          if (localLibraryId !== undefined) replacement = { originalId: localLibraryId, document: created }
          if (!isCurrent()) return
          const currentFile = filesRef.current.find((item) => item.id === fileId)
          if (currentFile === undefined) return
          libraryId = created.id
          const createdMetadata = created.metadata
          const targetDatasetId =
            normalizeParsingBackendCandidate(createdMetadata?.target_dataset_id) ?? file.datasetId ?? null
          const targetDatasetName =
            normalizeParsingBackendCandidate(createdMetadata?.target_dataset_name) ?? file.datasetName ?? null

          if (replacement === undefined) {
            setFiles((prev) =>
              prev.map((item) =>
                item.id === fileId
                  ? {
                      ...item,
                      libraryId,
                      librarySource: 'parsing_workspace',
                      datasetId: targetDatasetId,
                      datasetName: targetDatasetName,
                    }
                  : item,
              ),
            )
            upsertParsedFile({
              id: libraryId,
              filename: created.filename,
              fileType: created.file_type,
              fileSize: created.file_size,
              markdownContent: '',
              originalMarkdownContent: '',
              parsedAt: created.updated_at,
              parser: requestedLabel,
              parserBackend: requestedBackend,
              folderId: currentFile.folderId,
              datasetId: targetDatasetId,
              datasetName: targetDatasetName,
              source: 'parsing_workspace',
              status: mapBackendStatusToLibraryStatus(created.status),
              error: created.error_message === null ? undefined : created.error_message,
            })
          }
        }

        if (!isCurrent()) return

        if (replacement === undefined) {
          await updateParsedFile(libraryId, {
            status: 'parsing',
            error: undefined,
            parser: requestedLabel,
            parserBackend: requestedBackend,
          })
        }
        if (!isCurrent()) return

        const data = await parsingApi.parse(libraryId, {
          parser_backend: requestedBackend,
          image_caption_enabled: imageCaptionEnabled,
          image_ocr_enabled: imageOcrEnabled,
          vlm_correction_enabled: vlmCorrectionEnabled,
          signal: controller.signal,
        })

        if (!isCurrent()) return

        clearProgressInterval()

        const rawMarkdown = data.original_markdown_content
        const resolvedBackend = data.parser_backend
        const resolvedLabel = getParserLabel(resolvedBackend)
        const restored = restoreParsingRunFromMarkdown({
          rawMarkdown,
          cleanedMarkdown: data.markdown_content,
        })
        const markdownContent = restored.cleanedMarkdown
        const blocks = restored.blocks
        const durationSec = data.parse_duration_sec === null ? undefined : data.parse_duration_sec
        const runId = generateRequestId()
        const stats = buildParsingStatistics(markdownContent, blocks.length, data.stats)

        const run = {
          id: runId,
          parserBackend: resolvedBackend,
          parserLabel: resolvedLabel,
          rawMarkdown,
          cleanedMarkdown: markdownContent,
          blocks,
          elements: data.elements ?? undefined,
          createdAt: Date.now(),
          pdfQuality: data.pdf_quality ?? null,
          qualityGate: data.quality_gate ?? null,
          stats,
          durationSec,
        }

        const parsedContent = {
          contentLoaded: true as const,
          contentEdited: false,
          markdownContent,
          originalMarkdownContent: rawMarkdown,
          parser: resolvedLabel,
          parserBackend: resolvedBackend,
          durationSec,
          elements: data.elements ?? undefined,
          pdfQuality: data.pdf_quality ?? null,
          qualityGate: data.quality_gate ?? null,
          parsedAt: new Date().toISOString(),
          status: 'parsed' as const,
          error: undefined,
        }
        if (replacement !== undefined) {
          const { document: created, originalId } = replacement
          replaceParsedFile(originalId, {
            ...parsedContent,
            id: created.id,
            filename: created.filename,
            fileType: created.file_type,
            fileSize: created.file_size,
            source: 'parsing_workspace',
          })
          replacement = undefined
          setActiveLibraryFileId((current) => (current === originalId ? created.id : current))
          setSelectedGovernanceFileIds((current) => {
            if (!current.has(originalId)) return current
            const selected = new Set(current)
            selected.delete(originalId)
            selected.add(created.id)
            return selected
          })
          void saveDocSourceToCache({ id: created.id, file: file.file }, scope).catch((error) =>
            reportClientWarning('Failed to cache the parsed source file', error),
          )
        } else {
          try {
            await updateParsedFile(libraryId, parsedContent)
          } catch (error) {
            if (isCurrent()) {
              toast.error(`解析已完成，本地目录同步失败。${formatApiError(error, '请刷新文档目录')}`)
            }
          }
        }
        if (!isCurrent()) return

        setFiles((prev) =>
          prev.map((item) =>
            item.id === fileId
              ? {
                  ...item,
                  libraryId,
                  librarySource: 'parsing_workspace',
                  status: 'parsed',
                  markdownContent,
                  contentEdited: false,
                  parserBackend: resolvedBackend,
                  parserLabel: resolvedLabel,
                  parser: resolvedLabel,
                  progress: 100,
                  duration: durationSec,
                  stats,
                  elements: data.elements ?? undefined,
                  pdfQuality: data.pdf_quality ?? null,
                  qualityGate: data.quality_gate ?? null,
                  runs: [...(item.runs ?? []), run],
                  activeRunId: runId,
                  savedRunId: runId,
                }
              : item,
          ),
        )

        if (activeFileIdRef.current === fileId) {
          setActiveBlockId(null)
          setHoveredBlockId(null)
          setRightPanelMode('markdown')
        }
      } catch (err: unknown) {
        if (!isCurrent()) return

        const errorMessage = formatApiError(err, t('toasts.parseFailed'))
        const failure = parsingFailureSchema.safeParse(err)
        const diagnostics = failure.success ? failure.data.response.data.detail.diagnostics : undefined

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
              : item,
          ),
        )

        if (libraryId !== undefined && localLibraryId === undefined) {
          await updateParsedFile(libraryId, {
            status: 'error',
            error: errorMessage,
            parserBackend: requestedBackend,
          }).catch((error) => reportClientWarning('Failed to publish parsing failure to the library', error))
        }
      } finally {
        if (replacement !== undefined && scope === getAuthCacheScope() && revision === getAuthSessionRevision()) {
          const failedReplacement = replacement
          try {
            await parsingApi.delete(failedReplacement.document.id)
            if (scope === getAuthCacheScope() && revision === getAuthSessionRevision()) {
              await queryClient.cancelQueries({ queryKey: ['parsing', 'library-snapshot'] })
              if (scope === getAuthCacheScope() && revision === getAuthSessionRevision()) {
                removeParsedFile(failedReplacement.document.id)
                await queryClient.invalidateQueries({ queryKey: ['parsing', 'library-snapshot'] })
              }
            }
          } catch (error) {
            reportClientWarning('Failed to remove the unsuccessful parsing upload', error)
            if (isCurrent()) toast.warning('原本地记录已保留，但新上传文档清理失败，请在文档目录中检查')
          }
        }
        if (parseControllersRef.current.get(fileId) === controller) {
          parseControllersRef.current.delete(fileId)
        }
        clearProgressInterval()
      }
    },
    [
      cancelParse,
      filesRef,
      imageCaptionEnabled,
      imageOcrEnabled,
      parseControllersRef,
      parseProgressIntervalsRef,
      replaceParsedFile,
      removeParsedFile,
      restoreLibraryFileFromCache,
      queryClient,
      setActiveBlockId,
      setActiveLibraryFileId,
      setFiles,
      setHoveredBlockId,
      setRightPanelMode,
      setSelectedGovernanceFileIds,
      t,
      updateParsedFile,
      upsertParsedFile,
      vlmCorrectionEnabled,
    ],
  )

  useEffect(() => {
    if (!autoParseFileId) return
    const id = autoParseFileId
    setAutoParseFileId(null)
    void parseFile(id).catch((error) => reportClientWarning('Failed to start automatic parsing', error))
  }, [autoParseFileId, parseFile, setAutoParseFileId])

  const parseAllPending = useCallback(async () => {
    if (batchParseRef.current !== null) return
    const targets = visibleQueueFiles.filter(
      (file) => file.librarySource !== 'knowledge_base' && (file.status === 'pending' || file.status === 'error'),
    )
    const batch = new AbortController()
    const scope = getAuthCacheScope()
    const revision = getAuthSessionRevision()
    batchParseRef.current = batch
    try {
      for (const file of targets) {
        if (batch.signal.aborted || scope !== getAuthCacheScope() || revision !== getAuthSessionRevision()) break
        const current = filesRef.current.find((item) => item.id === file.id)
        if (current?.status === 'pending' || current?.status === 'error') await parseFile(current.id)
      }
    } finally {
      batchParseRef.current = null
    }
  }, [filesRef, parseFile, visibleQueueFiles])

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
            : file,
        ),
      )

      setActiveBlockId(null)
      setHoveredBlockId(null)
      setRightPanelMode('markdown')
    },
    [activeFile, setActiveBlockId, setFiles, setHoveredBlockId, setRightPanelMode],
  )

  const startKnowledgeParsing = useCallback(
    async (libraryId: string, backend: string) => {
      const file = useParsedFiles.getState().files.find((item) => item.id === libraryId)
      if (file?.source !== 'knowledge_base') return
      const key = `knowledge:${libraryId}`
      parseControllersRef.current.get(key)?.abort()
      const controller = new AbortController()
      parseControllersRef.current.set(key, controller)
      const scope = getAuthCacheScope()
      const revision = getAuthSessionRevision()
      const isCurrent = () =>
        !controller.signal.aborted &&
        parseControllersRef.current.get(key) === controller &&
        scope === getAuthCacheScope() &&
        revision === getAuthSessionRevision() &&
        useParsedFiles.getState().files.some((item) => item.id === libraryId)
      const resolved = resolveParserBackendForFilename(file.filename, backend)
      try {
        await documentApi.patchPipeline(libraryId, {
          patch: { persist_parsed_content: true, persist_parsed_content_max_chars: 2_000_000 },
          replace: false,
        })
        if (!isCurrent()) return
        await documentApi.retry(libraryId, { force: true, parser_backend: resolved.backend })
        if (!isCurrent()) return
        try {
          await updateParsedFile(libraryId, {
            error: undefined,
            parser: getParserLabel(resolved.backend),
            parserBackend: resolved.backend,
            status: 'parsing',
          })
        } catch (error) {
          if (isCurrent())
            toast.error(`解析请求已提交，但本地状态更新失败：${formatApiError(error, '无法更新文档状态')}`)
          return
        }
        if (isCurrent()) toast.success('已开始解析')
      } catch (error) {
        if (isCurrent()) toast.error(formatApiError(error, '开始解析失败'))
      } finally {
        if (parseControllersRef.current.get(key) === controller) parseControllersRef.current.delete(key)
      }
    },
    [parseControllersRef, updateParsedFile],
  )

  return {
    handleSelectRun,
    parseAllPending,
    parseFile,
    startKnowledgeParsing,
  }
}
