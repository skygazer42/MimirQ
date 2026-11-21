'use client'

import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState, type Dispatch, type SetStateAction } from 'react'

import { datasetApi } from '@/lib/api/datasets'
import { queryKeys } from '@/lib/query-keys'
import { documentApi } from '@/lib/api/documents'
import { listDocumentPages } from '@/lib/api/document-pages'
import { hasParsedFileMemoryContent, mergeDocumentLibrary } from '@/lib/document-library'
import { readPersistedParsingElements } from '@/lib/parsing-elements'
import { parsingApi } from '@/lib/api/parsing'
import { reportClientWarning } from '@/lib/client-logging'
import { getDocSourceFromCache } from '@/lib/doc-content-cache'
import { extractMarkdownHeadings } from '@/lib/markdown'
import { getParserLabel } from '@/lib/parser-options'
import { resolveParserBackendForFilename } from '@/lib/parser-compat'
import { restoreParsingRunFromMarkdown } from '@/lib/parsing-run-restore'
import { ROOT_FOLDER_ID, useParsedFiles, type FolderNode, type ParsedFileData } from '@/store/use-parsed-files-store'

import type { ParsedFile, ParseRun, ParsingLibrarySourceStatus } from './parsing-types'
import { loadParsingLibraryContent, type ParsingLibraryContentResult } from './parsing-library-content'
import {
  buildParsingStatistics,
  getActiveParsingRun,
  mapBackendStatusToLibraryStatus,
  normalizeParsingBackendCandidate,
  readParsingDurationSec,
} from './parsing-page-utils'

type UseParsingViewStateOptions = {
  activeFileId: string | null
  activeFolderId: string
  activeLibraryFileId: string | null
  files: ParsedFile[]
  folders: FolderNode[]
  isEditing: boolean
  isLibraryLoaded: boolean
  libraryFiles: ParsedFileData[]
  selectedDatasetId: string | null
  setActiveFileId: Dispatch<SetStateAction<string | null>>
  setActiveLibraryFileId: Dispatch<SetStateAction<string | null>>
  setParsedFiles: (files: ParsedFileData[]) => void
  updateParsedFile: (id: string, updates: Partial<Omit<ParsedFileData, 'id'>>) => Promise<void>
}

function mapParsingDocumentToLibraryFile(
  doc: Awaited<ReturnType<typeof parsingApi.listDocuments>>['items'][number],
  existing: ParsedFileData | undefined,
  datasetNameById: Map<string, string>,
): ParsedFileData {
  const meta = doc.metadata
  const serverElements = readPersistedParsingElements(meta?.elements)
  const durationSec = readParsingDurationSec(meta?.parse_duration_sec)
  const backendFromServer =
    normalizeParsingBackendCandidate(meta?.parser_backend) ??
    normalizeParsingBackendCandidate(meta?.parser_backend_requested) ??
    'auto'
  const preferredBackend =
    backendFromServer === 'auto' ? (existing?.parserBackend ?? backendFromServer) : backendFromServer
  const resolved = resolveParserBackendForFilename(doc.filename, preferredBackend)
  const backend = resolved.backend
  const status = mapBackendStatusToLibraryStatus(doc.status)
  const targetDatasetId = normalizeParsingBackendCandidate(meta?.target_dataset_id) ?? existing?.datasetId ?? null
  const targetDatasetName =
    normalizeParsingBackendCandidate(meta?.target_dataset_name) ??
    (targetDatasetId === null
      ? null
      : (datasetNameById.get(targetDatasetId) ?? existing?.datasetName ?? targetDatasetId))

  return {
    ...existing,
    id: doc.id,
    filename: doc.filename,
    fileType: doc.file_type,
    fileSize: doc.file_size,
    markdownContent: existing === undefined ? '' : existing.markdownContent,
    originalMarkdownContent: existing?.originalMarkdownContent,
    parsedAt: existing === undefined ? doc.updated_at : existing.parsedAt,
    parser: existing === undefined ? getParserLabel(backend) : existing.parser,
    parserBackend: existing === undefined ? backend : existing.parserBackend,
    durationSec: existing === undefined ? durationSec : existing.durationSec,
    elements: existing === undefined ? serverElements : existing.elements,
    contentEdited: existing === undefined ? meta?.edited === true : existing.contentEdited,
    folderId: existing?.folderId ?? ROOT_FOLDER_ID,
    datasetId: targetDatasetId,
    datasetName: targetDatasetName,
    source: 'parsing_workspace',
    status,
    error: status === 'error' && doc.error_message !== null ? doc.error_message : undefined,
  }
}

function mapKnowledgeDocumentToLibraryFile(
  doc: Awaited<ReturnType<typeof documentApi.list>>['items'][number],
  existing: ParsedFileData | undefined,
  datasetNameById: Map<string, string>,
): ParsedFileData {
  const meta = doc.metadata
  const serverElements = readPersistedParsingElements(meta?.elements)
  const durationSec = readParsingDurationSec(meta?.parse_duration_sec) ?? existing?.durationSec
  const backendFromServer =
    normalizeParsingBackendCandidate(meta?.parser_backend) ??
    normalizeParsingBackendCandidate(meta?.parser_backend_requested) ??
    existing?.parserBackend ??
    'auto'
  const resolved = resolveParserBackendForFilename(doc.filename, backendFromServer)
  const backend = resolved.backend
  const status = mapBackendStatusToLibraryStatus(doc.status)
  const datasetId = doc.dataset_id ?? null

  return {
    ...existing,
    id: doc.id,
    filename: doc.filename,
    fileType: doc.file_type,
    fileSize: doc.file_size,
    markdownContent: existing === undefined ? '' : existing.markdownContent,
    originalMarkdownContent: existing?.originalMarkdownContent,
    parsedAt: doc.updated_at,
    parser: getParserLabel(backend),
    parserBackend: backend,
    durationSec,
    elements: meta?.elements === undefined ? existing?.elements : serverElements,
    folderId: existing?.folderId ?? ROOT_FOLDER_ID,
    datasetId,
    datasetName:
      datasetId === null
        ? (existing?.datasetName ?? null)
        : (datasetNameById.get(datasetId) ?? existing?.datasetName ?? datasetId),
    source: 'knowledge_base',
    sourcePath: typeof meta?.source_path === 'string' ? meta.source_path : (existing?.sourcePath ?? null),
    status,
    error: status === 'error' && doc.error_message !== null ? doc.error_message : undefined,
  }
}

function isParsingWorkspaceDocument(doc: Awaited<ReturnType<typeof documentApi.list>>['items'][number]): boolean {
  const meta = doc.metadata
  return meta?.workspace === 'parsing'
}

function matchesLibraryContentVersion(file: ParsedFileData, requested: ParsedFileData): boolean {
  return (
    file.id === requested.id &&
    file.source === requested.source &&
    file.parsedAt === requested.parsedAt &&
    file.status === requested.status &&
    file.contentEdited === requested.contentEdited &&
    file.markdownContent === requested.markdownContent &&
    file.originalMarkdownContent === requested.originalMarkdownContent
  )
}

export function useParsingViewState({
  activeFileId,
  activeFolderId,
  activeLibraryFileId,
  files,
  folders,
  isEditing,
  isLibraryLoaded,
  libraryFiles,
  selectedDatasetId,
  setActiveFileId,
  setActiveLibraryFileId,
  setParsedFiles,
  updateParsedFile,
}: Readonly<UseParsingViewStateOptions>) {
  const datasetsQuery = useQuery({
    queryKey: queryKeys.datasets.exhaustive(),
    enabled: isLibraryLoaded,
    queryFn: ({ signal }) => datasetApi.listAll(undefined, { signal }),
    select: (datasets) => datasets.map((dataset) => ({ id: dataset.id, name: dataset.name })),
  })

  const availableDatasets = useMemo(() => datasetsQuery.data ?? [], [datasetsQuery.data])
  const datasetNameSignature = useMemo(
    () => availableDatasets.map((dataset) => `${dataset.id}:${dataset.name}`).join('|'),
    [availableDatasets],
  )
  const datasetNameById = useMemo(
    () => new Map(availableDatasets.map((dataset) => [dataset.id, dataset.name])),
    [availableDatasets],
  )

  const librarySyncQuery = useQuery({
    queryKey: ['parsing', 'library-snapshot', datasetNameSignature],
    enabled: isLibraryLoaded,
    queryFn: async ({ signal }) => {
      const knownFiles = new Map(useParsedFiles.getState().files.map((file) => [file.id, file]))
      const [parsingResult, knowledgeResult] = await Promise.allSettled([
        listDocumentPages((skip) => parsingApi.listDocuments({ skip, limit: 200 }, { signal }), signal).then(
          (documents) =>
            documents.map((doc) => mapParsingDocumentToLibraryFile(doc, knownFiles.get(doc.id), datasetNameById)),
        ),
        listDocumentPages((skip) => documentApi.list({ skip, limit: 200 }, { signal }), signal).then((documents) =>
          documents
            .filter((doc) => !isParsingWorkspaceDocument(doc))
            .map((doc) => mapKnowledgeDocumentToLibraryFile(doc, knownFiles.get(doc.id), datasetNameById)),
        ),
      ])
      signal.throwIfAborted()
      const errors: unknown[] = []
      if (parsingResult.status === 'rejected') errors.push(parsingResult.reason)
      if (knowledgeResult.status === 'rejected') errors.push(knowledgeResult.reason)
      return {
        knownFiles,
        parsingResult,
        knowledgeResult,
        error: errors.length === 0 ? null : new AggregateError(errors, '文档目录同步失败，已保留可用记录'),
      }
    },
  })

  const [libraryApplyError, setLibraryApplyError] = useState<Error | null>(null)

  useEffect(() => {
    const snapshot = librarySyncQuery.data
    if (!isLibraryLoaded || librarySyncQuery.isFetching || snapshot === undefined) return
    const current = useParsedFiles.getState().files
    const merged = mergeDocumentLibrary(current, snapshot)
    try {
      if (merged !== current) setParsedFiles(merged)
      setLibraryApplyError(null)
    } catch (error) {
      setLibraryApplyError(new Error('已读取文档目录，但同步到本地失败，请重试。', { cause: error }))
    }
  }, [isLibraryLoaded, librarySyncQuery.data, librarySyncQuery.isFetching, setParsedFiles])

  const librarySyncError =
    libraryApplyError ??
    (librarySyncQuery.error === null && librarySyncQuery.data !== undefined
      ? librarySyncQuery.data.error
      : librarySyncQuery.error)

  const queueFiles = useMemo(() => {
    const libraryById = new Map(libraryFiles.map((file) => [file.id, file]))
    return files.map((file) => {
      if (file.librarySource !== 'knowledge_base') return file
      const library = file.libraryId === undefined ? undefined : libraryById.get(file.libraryId)
      if (library === undefined) return file
      return {
        ...file,
        status: library.status ?? file.status,
        markdownContent: library.markdownContent,
        parserBackend: library.parserBackend ?? file.parserBackend,
        parserLabel: library.parser,
        duration: library.durationSec,
        elements: library.elements,
        error: library.error,
      }
    })
  }, [files, libraryFiles])
  const activeFile = queueFiles.find((file) => file.id === activeFileId) ?? null
  const activeLibraryFile = useMemo(() => {
    const libraryId = activeFile?.librarySource === 'knowledge_base' ? activeFile.libraryId : activeLibraryFileId
    return libraryFiles.find((file) => file.id === libraryId) ?? null
  }, [activeFile, activeLibraryFileId, libraryFiles])

  const librarySourceQuery = useQuery<ParsingLibrarySourceStatus>({
    queryKey: queryKeys.parsing.librarySource(activeLibraryFile?.id),
    enabled: isLibraryLoaded && activeFile === null && activeLibraryFile !== null,
    retry: false,
    staleTime: 0,
    queryFn: async ({ client, queryKey, signal }) => {
      if (activeLibraryFile === null) return 'unknown'
      const cached = await getDocSourceFromCache(activeLibraryFile.id)
      signal.throwIfAborted()
      if (cached !== null) return 'available'
      if (activeLibraryFile.source === undefined || client.getQueryData(queryKey) === 'missing') return 'missing'
      return 'unknown'
    },
  })
  const activeLibrarySourceStatus: ParsingLibrarySourceStatus = librarySourceQuery.isError
    ? 'unknown'
    : (librarySourceQuery.data ?? 'unknown')

  const activeLibraryContentPollInterval =
    activeLibraryFile &&
    activeLibraryFile.source === 'knowledge_base' &&
    (activeLibraryFile.status === 'pending' || activeLibraryFile.status === 'parsing')
      ? 2_000
      : false

  const activeLibraryContentQuery = useQuery<{ file: ParsedFileData; result: ParsingLibraryContentResult } | null>({
    queryKey: [
      'parsing',
      'library-content',
      activeLibraryFile?.id,
      activeLibraryFile?.source,
      activeLibraryFile?.parsedAt,
      activeLibraryFile?.status,
    ],
    enabled: isLibraryLoaded && activeLibraryFile !== null,
    retry: false,
    refetchInterval: (query) => (query.state.error === null ? activeLibraryContentPollInterval : false),
    staleTime: 0,
    structuralSharing: false,
    queryFn: async ({ signal }) => {
      if (activeLibraryFile === null) return null
      const result = await loadParsingLibraryContent(activeLibraryFile, { signal })
      signal.throwIfAborted()
      return { file: activeLibraryFile, result }
    },
  })

  useEffect(() => {
    const snapshot = activeLibraryContentQuery.data
    if (!isLibraryLoaded || snapshot === undefined || snapshot === null) return
    const file = useParsedFiles.getState().files.find((item) => item.id === snapshot.file.id)
    if (file === undefined || !matchesLibraryContentVersion(file, snapshot.file)) return
    const { result } = snapshot
    const content = result.content
    if (
      result.status === file.status &&
      result.error === file.error &&
      (content === undefined ||
        (content.markdownContent === file.markdownContent &&
          content.originalMarkdownContent === file.originalMarkdownContent &&
          content.contentLoaded === file.contentLoaded &&
          content.contentEdited === file.contentEdited &&
          content.parser === file.parser &&
          content.parserBackend === file.parserBackend &&
          content.durationSec === file.durationSec &&
          content.elements === file.elements &&
          content.pdfQuality === file.pdfQuality &&
          content.qualityGate === file.qualityGate))
    )
      return
    void updateParsedFile(file.id, { ...content, status: result.status, error: result.error }).catch((error) => {
      reportClientWarning('Failed to update parsed library content', error)
    })
  }, [activeLibraryContentQuery.data, activeLibraryFileId, isLibraryLoaded, updateParsedFile])

  const activeRun = useMemo<ParseRun | null>(() => {
    if (!activeFile) return null
    if (activeFile.librarySource === 'knowledge_base' && activeLibraryFile !== null) {
      if (activeFile.status !== 'parsed') return null
      const rawMarkdown = activeLibraryFile.originalMarkdownContent ?? activeLibraryFile.markdownContent
      const restored = restoreParsingRunFromMarkdown({
        rawMarkdown,
        cleanedMarkdown: activeLibraryFile.markdownContent,
      })
      return {
        id: activeFile.id,
        parserBackend: activeFile.parserBackend,
        parserLabel: activeFile.parserLabel,
        rawMarkdown,
        cleanedMarkdown: restored.cleanedMarkdown,
        blocks: restored.blocks,
        elements: activeLibraryFile.elements,
        pdfQuality: activeLibraryFile.pdfQuality,
        qualityGate: activeLibraryFile.qualityGate,
        stats: buildParsingStatistics(restored.cleanedMarkdown, restored.blocks.length),
        durationSec: activeLibraryFile.durationSec,
        createdAt: Date.parse(activeLibraryFile.parsedAt),
      }
    }
    return getActiveParsingRun(activeFile) ?? null
  }, [activeFile, activeLibraryFile])

  const isRunUnavailable =
    activeFile !== null &&
    activeFile.librarySource !== 'knowledge_base' &&
    activeFile.activeRunId !== undefined &&
    activeRun === null
  const libraryContent = activeLibraryContentQuery.data
  const acceptedLibraryContent =
    activeLibraryFile !== null &&
    libraryContent != null &&
    matchesLibraryContentVersion(activeLibraryFile, libraryContent.file)
      ? libraryContent.result.content
      : undefined
  const activeLibraryMarkdown = acceptedLibraryContent?.markdownContent ?? activeLibraryFile?.markdownContent
  const activeSavedMarkdown = isRunUnavailable ? '' : (activeFile?.markdownContent ?? activeLibraryMarkdown ?? '')
  const activeMarkdown = activeRun === null ? activeSavedMarkdown : activeRun.cleanedMarkdown
  const activeResult = isRunUnavailable ? null : (activeRun ?? activeFile ?? activeLibraryFile)
  const activeQualityGate = activeResult?.qualityGate
  const activePdfQuality = activeResult?.pdfQuality
  const activeElements = useMemo(() => activeResult?.elements ?? [], [activeResult])
  const activeBlocksWithPositions = useMemo(
    () => activeRun?.blocks.filter((block) => block.positions.length > 0) ?? [],
    [activeRun?.blocks],
  )
  const isPdf = activeFile?.file.name.toLowerCase().endsWith('.pdf') ?? false
  const tocEnabled = useMemo(
    () => extractMarkdownHeadings(activeMarkdown, { maxDepth: 4 }).length > 0,
    [activeMarkdown],
  )

  const folderPathById = useMemo(() => {
    const byId = new Map(folders.map((folder) => [folder.id, folder]))
    const cache = new Map<string, string>()

    const getPath = (folderId: string): string => {
      if (folderId === ROOT_FOLDER_ID) return '根目录'
      const cached = cache.get(folderId)
      if (cached) return cached
      const node = byId.get(folderId)
      if (node === undefined) throw new Error(`目录不存在：${folderId}`)
      const parentPath = node.parentId === ROOT_FOLDER_ID ? '根目录' : getPath(node.parentId)
      const path = `${parentPath} / ${node.name}`
      cache.set(folderId, path)
      return path
    }

    const result: Record<string, string> = { [ROOT_FOLDER_ID]: '根目录' }
    for (const folder of folders) result[folder.id] = getPath(folder.id)
    return result
  }, [folders])

  const currentFolderId = activeFolderId
  const visibleQueueFiles = useMemo(() => {
    if (selectedDatasetId !== null) {
      return queueFiles
        .filter((file) => file.datasetId === selectedDatasetId)
        .sort((a, b) => (b.createdAt ?? 0) - (a.createdAt ?? 0))
    }
    return queueFiles
      .filter((file) => file.folderId === currentFolderId)
      .sort((a, b) => (b.createdAt ?? 0) - (a.createdAt ?? 0))
  }, [currentFolderId, queueFiles, selectedDatasetId])

  const visibleLibraryFiles = useMemo(() => {
    return libraryFiles
      .filter((file) => {
        if (selectedDatasetId !== null) {
          return (
            (file.source === 'knowledge_base' || file.source === 'parsing_workspace') &&
            file.datasetId === selectedDatasetId
          )
        }
        return (file.folderId ?? ROOT_FOLDER_ID) === currentFolderId
      })
      .sort((a, b) => Date.parse(b.parsedAt) - Date.parse(a.parsedAt))
  }, [currentFolderId, libraryFiles, selectedDatasetId])

  const queueLibraryIdSet = useMemo(() => {
    const ids = new Set<string>()
    for (const file of files) {
      if (file.libraryId !== undefined) ids.add(file.libraryId)
    }
    return ids
  }, [files])

  const visibleLibraryOnlyFiles = useMemo(() => {
    return visibleLibraryFiles.filter((file) => !queueLibraryIdSet.has(file.id))
  }, [queueLibraryIdSet, visibleLibraryFiles])

  useEffect(() => {
    if (isEditing) return
    if (activeLibraryFileId !== null) {
      const linkedQueueFile = visibleQueueFiles.find((file) => file.libraryId === activeLibraryFileId)
      if (linkedQueueFile !== undefined) {
        setActiveFileId(linkedQueueFile.id)
        setActiveLibraryFileId(null)
      }
      return
    }
    if (visibleQueueFiles.length === 0) {
      if (activeFileId) setActiveFileId(null)
      return
    }

    const stillVisible = activeFileId && visibleQueueFiles.some((file) => file.id === activeFileId)
    if (!stillVisible) {
      setActiveFileId(visibleQueueFiles[0].id)
    }
  }, [activeFileId, activeLibraryFileId, isEditing, setActiveFileId, setActiveLibraryFileId, visibleQueueFiles])

  return {
    activeBlocksWithPositions,
    activeFile,
    activeLibraryFile,
    activeLibrarySourceStatus,
    activeLibrarySourceError: librarySourceQuery.error,
    isLibrarySourceChecking: librarySourceQuery.isFetching,
    retryLibrarySource: () => void librarySourceQuery.refetch(),
    activeLibraryContentError: activeLibraryContentQuery.error,
    isLibraryContentLoading: activeLibraryContentQuery.isFetching,
    hasLibraryContent:
      acceptedLibraryContent !== undefined ||
      (activeLibraryFile !== null && hasParsedFileMemoryContent(activeLibraryFile)),
    retryLibraryContent: () => void activeLibraryContentQuery.refetch(),
    activeMarkdown,
    activeElements,
    activePdfQuality,
    activeQualityGate,
    activeRun,
    isRunUnavailable,
    availableDatasets,
    datasetsError: datasetsQuery.error,
    librarySyncError,
    isLibrarySyncing: librarySyncQuery.isFetching,
    retryLibrarySync: () => void librarySyncQuery.refetch(),
    currentFolderId,
    queueFiles,
    folderPathById,
    isPdf,
    tocEnabled,
    visibleLibraryOnlyFiles,
    visibleQueueFiles,
  }
}
