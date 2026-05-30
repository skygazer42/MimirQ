'use client'

import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, type Dispatch, type SetStateAction } from 'react'

import { toast } from 'sonner'

import { datasetApi, documentApi, parsingApi } from '@/lib/api'
import { getDocContentFromCache, getDocSourceFromCache } from '@/lib/doc-content-cache'
import { extractMarkdownHeadings } from '@/lib/markdown'
import { getParserLabel } from '@/lib/parser-options'
import { resolveParserBackendForFilename } from '@/lib/parser-compat'
import { shouldRefreshParsingContentFromRemote } from '@/lib/parsing-run-restore'
import { ROOT_FOLDER_ID, useParsedFiles, type FolderNode, type ParsedFileData } from '@/store/use-parsed-files-store'
import { type FileStatus } from '@/components/ui/file-queue-item'

import type { ParsingElement } from '@/lib/api/parsing'
import type { ParsedFile } from './parsing-types'

type MutableRef<T> = {
  current: T
}

const normalizeBackendCandidate = (value: unknown): string =>
  typeof value === 'string' && value.trim() ? value.trim() : ''

type SourceStatus = 'unknown' | 'available' | 'missing'

type UseParsingViewStateOptions = {
  activeFileId: string | null
  activeFolderId: string
  activeLibraryFileId: string | null
  didSyncLibraryFromServerRef: MutableRef<boolean>
  files: ParsedFile[]
  folders: FolderNode[]
  isLibraryLoaded: boolean
  libraryFiles: ParsedFileData[]
  mapBackendStatusToLibraryStatus: (status?: string) => FileStatus
  mountLibraryFileToQueue: (
    libraryId: string,
    sourceFile: File,
    options?: { autoParse?: boolean; select?: boolean }
  ) => Promise<string | null>
  rehydratedFolderIdsRef: MutableRef<Set<string>>
  selectedDatasetId: string | null
  setActiveFileId: Dispatch<SetStateAction<string | null>>
  setActiveLibrarySourceStatus: Dispatch<SetStateAction<SourceStatus>>
  setIsQueueRehydrating: Dispatch<SetStateAction<boolean>>
  setParsedFiles: (files: ParsedFileData[]) => void
  updateParsedFile: (id: string, updates: Partial<Omit<ParsedFileData, 'id'>>) => void
}

type DatasetOption = {
  id: string
  name: string
}

type ParsingLibraryContentHydration = {
  markdownContent: string
  originalMarkdownContent: string
  status: FileStatus
  parser?: string
  parserBackend?: string
  durationSec?: number
  elements?: ParsingElement[]
} | null

function mapParsingDocumentToLibraryFile(
  doc: Awaited<ReturnType<typeof parsingApi.listDocuments>>['items'][number],
  currentFiles: ParsedFileData[],
  mapBackendStatusToLibraryStatus: (status?: string) => FileStatus
): ParsedFileData {
  const byId = new Map(currentFiles.map((file) => [file.id, file]))
  const id = String(doc.id || '').trim()
  const existing = byId.get(id)
  const meta = doc.metadata
  const rawDuration = meta?.parse_duration_sec
  const durationSec = Number.isFinite(Number(rawDuration)) ? Number(rawDuration) : existing?.durationSec
  const backendFromServer =
    normalizeBackendCandidate(meta?.parser_backend) ||
    normalizeBackendCandidate(meta?.parser_backend_requested) ||
    'auto'
  const preferredBackend =
    backendFromServer === 'auto' ? (existing?.parserBackend || backendFromServer) : backendFromServer
  const resolved = resolveParserBackendForFilename(doc.filename || existing?.filename || 'document', preferredBackend)
  const backend = resolved.backend
  const status = mapBackendStatusToLibraryStatus(doc.status)

  return {
    id,
    filename: doc.filename || existing?.filename || 'document',
    fileType: doc.file_type || existing?.fileType || '',
    fileSize: Number(doc.file_size || existing?.fileSize || 0),
    markdownContent: existing?.markdownContent || '',
    originalMarkdownContent: existing?.originalMarkdownContent || '',
    parsedAt: String(doc.updated_at || doc.created_at || existing?.parsedAt || new Date().toISOString()),
    parser: getParserLabel(backend),
    parserBackend: backend,
    durationSec,
    elements: existing?.elements || [],
    folderId: existing?.folderId || ROOT_FOLDER_ID,
    datasetId: doc.dataset_id || null,
    datasetName: existing?.datasetName || null,
    source: 'parsing_workspace',
    status,
    error: status === 'error' ? String(doc.error_message || existing?.error || '解析失败') : undefined,
  }
}

function mapKnowledgeDocumentToLibraryFile(
  doc: Awaited<ReturnType<typeof documentApi.list>>['items'][number],
  currentFiles: ParsedFileData[],
  mapBackendStatusToLibraryStatus: (status?: string) => FileStatus,
  datasetNameById: Map<string, string>
): ParsedFileData {
  const byId = new Map(currentFiles.map((file) => [file.id, file]))
  const id = String(doc.id || '').trim()
  const existing = byId.get(id)
  const meta = doc.metadata
  const rawDuration = meta?.parse_duration_sec
  const durationSec = Number.isFinite(Number(rawDuration)) ? Number(rawDuration) : existing?.durationSec
  const backendFromServer =
    normalizeBackendCandidate(meta?.parser_backend) ||
    normalizeBackendCandidate(meta?.parser_backend_requested) ||
    existing?.parserBackend ||
    'auto'
  const resolved = resolveParserBackendForFilename(doc.filename || existing?.filename || 'document', backendFromServer)
  const backend = resolved.backend
  const status = mapBackendStatusToLibraryStatus(doc.status)
  const datasetId = doc.dataset_id || null

  return {
    id,
    filename: doc.filename || existing?.filename || 'document',
    fileType: doc.file_type || existing?.fileType || '',
    fileSize: Number(doc.file_size || existing?.fileSize || 0),
    markdownContent: existing?.markdownContent || '',
    originalMarkdownContent: existing?.originalMarkdownContent || '',
    parsedAt: String(doc.updated_at || doc.created_at || existing?.parsedAt || new Date().toISOString()),
    parser: getParserLabel(backend),
    parserBackend: backend,
    durationSec,
    elements: existing?.elements || [],
    folderId: existing?.folderId || ROOT_FOLDER_ID,
    datasetId,
    datasetName: datasetId ? datasetNameById.get(datasetId) || existing?.datasetName || datasetId : existing?.datasetName || null,
    source: 'knowledge_base',
    sourcePath: typeof meta?.source_path === 'string' ? meta.source_path : existing?.sourcePath || null,
    status,
    error: status === 'error' ? String(doc.error_message || existing?.error || '入库失败') : undefined,
  }
}

function isParsingWorkspaceDocument(doc: Awaited<ReturnType<typeof documentApi.list>>['items'][number]): boolean {
  const meta = doc.metadata
  return meta?.workspace === 'parsing'
}

async function hydrateLibraryContent(
  id: string,
  status: FileStatus,
  options?: { fileType?: string | null; source?: ParsedFileData['source'] }
): Promise<ParsingLibraryContentHydration> {
  let cachedFallback: ParsingLibraryContentHydration = null
  try {
    const cached = await getDocContentFromCache(id)
    const markdown = (cached?.markdownContent || '').trim()
    const original = (cached?.originalMarkdownContent || '').trim()
    if (markdown || original) {
      cachedFallback = {
        markdownContent: markdown || original,
        originalMarkdownContent: original || markdown,
        status: status || 'parsed',
      }
      if (
        !shouldRefreshParsingContentFromRemote({
          fileType: options?.fileType,
          originalMarkdownContent: original || markdown,
        })
      ) {
        return cachedFallback
      }
    }
  } catch {
    // ignore cache miss and fall back to backend
  }

  if (options?.source === 'knowledge_base') {
    try {
      const remote = await documentApi.getParsedContent(id, { max_chars: 2_000_000 })
      if (!remote?.available) return cachedFallback

      const markdown = (remote.markdown_content || '').trim()
      const original = (remote.original_markdown_content || '').trim()
      if (!markdown && !original) return cachedFallback

      const persistedMeta =
        remote.persisted_meta && typeof remote.persisted_meta === 'object'
          ? (remote.persisted_meta as Record<string, unknown>)
          : {}
      const backend =
        normalizeBackendCandidate(persistedMeta.parser_backend) ||
        normalizeBackendCandidate(persistedMeta.parser_backend_requested) ||
        'auto'
      const rawDuration = persistedMeta.parse_duration_sec
      const durationSec = Number.isFinite(Number(rawDuration)) ? Number(rawDuration) : undefined

      return {
        markdownContent: markdown || original,
        originalMarkdownContent: original || markdown,
        status: 'parsed',
        parser: getParserLabel(backend),
        parserBackend: backend,
        durationSec,
      }
    } catch {
      // ignore backend content load failures for passive selection
      return cachedFallback
    }
  }

  try {
    const remote = await parsingApi.getContent(id)
    const markdown = (remote?.markdown_content || '').trim()
    const original = (remote?.original_markdown_content || '').trim()
    const rawDuration = remote?.parse_duration_sec
    const durationSec = Number.isFinite(Number(rawDuration)) ? Number(rawDuration) : undefined
    if (!markdown && !original) return null
    return {
      markdownContent: markdown || original,
      originalMarkdownContent: original || markdown,
      status: status || 'parsed',
      parser: getParserLabel(remote?.parser_backend || 'auto'),
      parserBackend: String(remote?.parser_backend || 'auto'),
      durationSec,
      elements: remote?.elements || [],
    }
  } catch {
    // ignore backend content load failures for passive selection
    return cachedFallback
  }
}

export function useParsingViewState({
  activeFileId,
  activeFolderId,
  activeLibraryFileId,
  didSyncLibraryFromServerRef,
  files,
  folders,
  isLibraryLoaded,
  libraryFiles,
  mapBackendStatusToLibraryStatus,
  mountLibraryFileToQueue,
  rehydratedFolderIdsRef,
  selectedDatasetId,
  setActiveFileId,
  setActiveLibrarySourceStatus,
  setIsQueueRehydrating,
  setParsedFiles,
  updateParsedFile,
}: Readonly<UseParsingViewStateOptions>) {
  const datasetsQuery = useQuery({
    queryKey: ['parsing', 'datasets'],
    enabled: isLibraryLoaded,
    queryFn: async (): Promise<DatasetOption[]> => {
      try {
        const response = await datasetApi.list({ skip: 0, limit: 200 })
        return (response.items || []).map((dataset) => ({
          id: String(dataset.id),
          name: dataset.name || String(dataset.id),
        }))
      } catch (err) {
        console.warn('Failed to sync datasets for parsing workspace:', err)
        return []
      }
    },
  })

  const availableDatasets = useMemo(() => datasetsQuery.data || [], [datasetsQuery.data])
  const datasetNameSignature = useMemo(
    () => availableDatasets.map((dataset) => `${dataset.id}:${dataset.name}`).join('|'),
    [availableDatasets]
  )
  const datasetNameById = useMemo(
    () => new Map(availableDatasets.map((dataset) => [dataset.id, dataset.name])),
    [availableDatasets]
  )

  const librarySyncQuery = useQuery({
    queryKey: ['parsing', 'library-documents', datasetNameSignature],
    enabled: isLibraryLoaded,
    queryFn: async () => {
      const [parsingResult, knowledgeResult] = await Promise.allSettled([
        parsingApi.listDocuments({ skip: 0, limit: 200 }),
        documentApi.list({ skip: 0, limit: 200 }),
      ])

      if (parsingResult.status === 'rejected' && knowledgeResult.status === 'rejected') {
        console.warn('Failed to sync parsing and knowledge documents:', parsingResult.reason, knowledgeResult.reason)
        return null
      }

      if (parsingResult.status === 'rejected') {
        console.warn('Failed to sync parsing library from server:', parsingResult.reason)
      }
      if (knowledgeResult.status === 'rejected') {
        console.warn('Failed to sync knowledge documents into parsing workspace:', knowledgeResult.reason)
      }

      const current = useParsedFiles.getState().files || []
      const parsingItems = parsingResult.status === 'fulfilled' ? parsingResult.value.items || [] : []
      const knowledgeItems = knowledgeResult.status === 'fulfilled' ? knowledgeResult.value.items || [] : []

      try {
        return [
          ...parsingItems.map((doc) =>
            mapParsingDocumentToLibraryFile(doc, current, mapBackendStatusToLibraryStatus)
          ),
          ...knowledgeItems
            .filter((doc) => !isParsingWorkspaceDocument(doc))
            .map((doc) =>
              mapKnowledgeDocumentToLibraryFile(doc, current, mapBackendStatusToLibraryStatus, datasetNameById)
            ),
        ]
      } catch (err) {
        console.warn('Failed to sync parsing library from server:', err)
        return null
      }
    },
  })

  useEffect(() => {
    if (!librarySyncQuery.data) return
    didSyncLibraryFromServerRef.current = true
    setParsedFiles(librarySyncQuery.data)
  }, [didSyncLibraryFromServerRef, librarySyncQuery.data, setParsedFiles])

  const activeFile = files.find((file) => file.id === activeFileId) || null

  const activeLibraryFile = useMemo(() => {
    if (!activeLibraryFileId) return null
    return libraryFiles.find((file) => file.id === activeLibraryFileId) || null
  }, [activeLibraryFileId, libraryFiles])

  const activeLibraryContentQuery = useQuery({
    queryKey: ['parsing', 'library-content', activeLibraryFileId, activeLibraryFile?.source],
    enabled: Boolean(
      activeLibraryFileId &&
        activeLibraryFile &&
        (
          !(activeLibraryFile.markdownContent || '').trim() ||
          shouldRefreshParsingContentFromRemote({
            fileType: activeLibraryFile.fileType,
            originalMarkdownContent:
              activeLibraryFile.originalMarkdownContent || activeLibraryFile.markdownContent,
          })
        )
    ),
    retry: false,
    staleTime: 0,
    queryFn: async () => {
      if (!activeLibraryFileId || !activeLibraryFile) return null
      return hydrateLibraryContent(activeLibraryFileId, activeLibraryFile.status || 'parsed', {
        fileType: activeLibraryFile.fileType,
        source: activeLibraryFile.source,
      })
    },
  })

  useEffect(() => {
    const id = (activeLibraryFileId || '').trim()
    if (!id || !activeLibraryContentQuery.data) return
    updateParsedFile(id, activeLibraryContentQuery.data)
  }, [activeLibraryContentQuery.data, activeLibraryFileId, updateParsedFile])

  useEffect(() => {
    const id = (activeLibraryFileId || '').trim()
    if (!id) {
      setActiveLibrarySourceStatus('unknown')
      return
    }

    setActiveLibrarySourceStatus('available')
  }, [activeLibraryFileId, setActiveLibrarySourceStatus])

  const activeRun = useMemo(() => {
    if (!activeFile) return null
    const runs = activeFile.runs || []
    if (!runs.length) return null
    const selected = runs.find((run) => run.id === activeFile.activeRunId)
    return selected || runs.at(-1) || null
  }, [activeFile])

  const activeMarkdown =
    activeRun?.cleanedMarkdown || activeFile?.markdownContent || activeLibraryFile?.markdownContent || ''
  const activeQualityGate = activeRun?.qualityGate || activeFile?.qualityGate || null
  const activePdfQuality = activeRun?.pdfQuality || activeFile?.pdfQuality || null
  const activeElements = activeRun?.elements || activeFile?.elements || []
  const activeBlocksWithPositions = useMemo(
    () => (activeRun?.blocks || []).filter((block) => (block.positions || []).length > 0),
    [activeRun?.blocks]
  )
  const isPdf = Boolean(activeFile?.file?.name?.toLowerCase().endsWith('.pdf'))
  const tocEnabled = useMemo(() => extractMarkdownHeadings(activeMarkdown, { maxDepth: 4 }).length > 0, [activeMarkdown])

  const folderPathById = useMemo(() => {
    const byId = new Map(folders.map((folder) => [folder.id, folder]))
    const cache = new Map<string, string>()

    const getPath = (folderId: string): string => {
      if (!folderId || folderId === ROOT_FOLDER_ID) return '根目录'
      const cached = cache.get(folderId)
      if (cached) return cached
      const node = byId.get(folderId)
      if (!node) return '根目录'
      const parentPath = node.parentId && node.parentId !== ROOT_FOLDER_ID ? getPath(node.parentId) : '根目录'
      const path = `${parentPath} / ${node.name}`
      cache.set(folderId, path)
      return path
    }

    const result: Record<string, string> = { [ROOT_FOLDER_ID]: '根目录' }
    for (const folder of folders) result[folder.id] = getPath(folder.id)
    return result
  }, [folders])

  const currentFolderId = activeFolderId || ROOT_FOLDER_ID
  const visibleQueueFiles = useMemo(() => {
    if (selectedDatasetId) {
      return activeFileId ? files.filter((file) => file.id === activeFileId) : []
    }
    return files
      .filter((file) => (file.folderId || ROOT_FOLDER_ID) === currentFolderId)
      .sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0))
  }, [activeFileId, currentFolderId, files, selectedDatasetId])

  const visibleLibraryFiles = useMemo(() => {
    return libraryFiles
      .filter((file) => {
        if (selectedDatasetId) {
          return file.source === 'knowledge_base' && file.datasetId === selectedDatasetId
        }
        return (file.folderId || ROOT_FOLDER_ID) === currentFolderId
      })
      .sort((a, b) => Date.parse(b.parsedAt) - Date.parse(a.parsedAt))
  }, [currentFolderId, libraryFiles, selectedDatasetId])

  const queueLibraryIdSet = useMemo(() => {
    const ids = new Set<string>()
    for (const file of files) {
      if (file.libraryId) ids.add(file.libraryId)
    }
    return ids
  }, [files])

  const visibleLibraryOnlyFiles = useMemo(() => {
    return visibleLibraryFiles.filter((file) => !queueLibraryIdSet.has(file.id))
  }, [queueLibraryIdSet, visibleLibraryFiles])

  useEffect(() => {
    if (!isLibraryLoaded) return

    const folderId = currentFolderId
    if (!folderId) return
    if (rehydratedFolderIdsRef.current.has(folderId)) return

    const candidates = visibleLibraryOnlyFiles.filter((file) => {
      const status = file.status || 'parsed'
      if (file.source === 'knowledge_base') return false
      return status === 'pending' || status === 'error' || status === 'parsing'
    })

    rehydratedFolderIdsRef.current.add(folderId)
    if (candidates.length === 0) return

    let cancelled = false
    setIsQueueRehydrating(true)

    ;(async () => {
      let missing = 0

      for (const entry of candidates) {
        if (cancelled) return

        try {
          const cached = await getDocSourceFromCache(entry.id)
          if (!cached) {
            missing += 1
            continue
          }

          const file = new File([cached.blob], cached.filename || entry.filename, {
            type: cached.mimeType || 'application/octet-stream',
            lastModified: cached.lastModified || Date.now(),
          })

          await mountLibraryFileToQueue(entry.id, file, { select: false })
        } catch {
          missing += 1
        }
      }

      if (cancelled) return
      if (missing > 0) toast.warning(`有 ${missing} 个文件未在本地缓存源文件，需要预览时将从服务器下载`)
    })().finally(() => {
      if (!cancelled) setIsQueueRehydrating(false)
    })

    return () => {
      cancelled = true
    }
  }, [
    currentFolderId,
    isLibraryLoaded,
    mountLibraryFileToQueue,
    rehydratedFolderIdsRef,
    setIsQueueRehydrating,
    visibleLibraryOnlyFiles,
  ])

  useEffect(() => {
    if (visibleQueueFiles.length === 0) {
      if (activeFileId) setActiveFileId(null)
      return
    }

    const stillVisible = activeFileId && visibleQueueFiles.some((file) => file.id === activeFileId)
    if (!stillVisible && !activeLibraryFileId) {
      setActiveFileId(visibleQueueFiles[0].id)
    }
  }, [activeFileId, activeLibraryFileId, setActiveFileId, visibleQueueFiles])

  return {
    activeBlocksWithPositions,
    activeFile,
    activeLibraryFile,
    activeLibraryFolderId: activeLibraryFile?.folderId || ROOT_FOLDER_ID,
    activeMarkdown,
    activeElements,
    activePdfQuality,
    activeQualityGate,
    activeRun,
    availableDatasets,
    currentFolderId,
    folderPathById,
    isPdf,
    tocEnabled,
    visibleLibraryOnlyFiles,
    visibleQueueFiles,
  }
}
