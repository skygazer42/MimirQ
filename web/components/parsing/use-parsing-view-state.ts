'use client'

import { useCallback, useEffect, useMemo, type Dispatch, type SetStateAction } from 'react'

import { toast } from 'sonner'

import { parsingApi } from '@/lib/api'
import { getDocContentFromCache, getDocSourceFromCache } from '@/lib/doc-content-cache'
import { extractMarkdownHeadings } from '@/lib/markdown'
import { getParserLabel } from '@/lib/parser-options'
import { resolveParserBackendForFilename } from '@/lib/parser-compat'
import { ROOT_FOLDER_ID, useParsedFiles, type FolderNode, type ParsedFileData } from '@/store/use-parsed-files-store'
import { type FileStatus } from '@/components/ui/file-queue-item'

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
  setActiveFileId: Dispatch<SetStateAction<string | null>>
  setActiveLibrarySourceStatus: Dispatch<SetStateAction<SourceStatus>>
  setIsQueueRehydrating: Dispatch<SetStateAction<boolean>>
  setParsedFiles: (files: ParsedFileData[]) => void
  updateParsedFile: (id: string, updates: Partial<Omit<ParsedFileData, 'id'>>) => void
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
  setActiveFileId,
  setActiveLibrarySourceStatus,
  setIsQueueRehydrating,
  setParsedFiles,
  updateParsedFile,
}: Readonly<UseParsingViewStateOptions>) {
  const syncLibraryFromServer = useCallback(async () => {
    try {
      const { items } = await parsingApi.listDocuments({ skip: 0, limit: 500 })
      const current = useParsedFiles.getState().files || []
      const byId = new Map(current.map((file) => [file.id, file]))

      const next = items.map((doc) => {
        const id = String(doc.id || '').trim()
        const existing = byId.get(id)
        const meta = doc.metadata as Record<string, unknown> | undefined
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
          folderId: existing?.folderId || ROOT_FOLDER_ID,
          status,
          error: status === 'error' ? String(doc.error_message || existing?.error || '解析失败') : undefined,
        }
      })

      setParsedFiles(next)
    } catch (err) {
      console.warn('Failed to sync parsing library from server:', err)
    }
  }, [mapBackendStatusToLibraryStatus, setParsedFiles])

  useEffect(() => {
    if (!isLibraryLoaded) return
    if (didSyncLibraryFromServerRef.current) return
    didSyncLibraryFromServerRef.current = true
    void syncLibraryFromServer()
  }, [didSyncLibraryFromServerRef, isLibraryLoaded, syncLibraryFromServer])

  const activeFile = files.find((file) => file.id === activeFileId) || null

  const activeLibraryFile = useMemo(() => {
    if (!activeLibraryFileId) return null
    return libraryFiles.find((file) => file.id === activeLibraryFileId) || null
  }, [activeLibraryFileId, libraryFiles])

  useEffect(() => {
    const id = (activeLibraryFileId || '').trim()
    if (!id) return
    const file = activeLibraryFile
    if (!file) return
    if ((file.markdownContent || '').trim()) return

    let cancelled = false
    ;(async () => {
      try {
        const cached = await getDocContentFromCache(id)
        if (cancelled) return
        const markdown = (cached?.markdownContent || '').trim()
        const original = (cached?.originalMarkdownContent || '').trim()
        if (markdown || original) {
          updateParsedFile(id, {
            markdownContent: markdown || original,
            originalMarkdownContent: original || markdown,
            status: file.status || 'parsed',
          })
          return
        }
      } catch {
        // ignore cache miss and fall back to backend
      }

      try {
        const remote = await parsingApi.getContent(id)
        if (cancelled) return
        const markdown = (remote?.markdown_content || '').trim()
        const original = (remote?.original_markdown_content || '').trim()
        const rawDuration = remote?.parse_duration_sec
        const durationSec = Number.isFinite(Number(rawDuration)) ? Number(rawDuration) : undefined
        if (!markdown && !original) return
        updateParsedFile(id, {
          markdownContent: markdown || original,
          originalMarkdownContent: original || markdown,
          status: file.status || 'parsed',
          parser: getParserLabel(remote?.parser_backend || 'auto'),
          parserBackend: String(remote?.parser_backend || 'auto'),
          durationSec,
        })
      } catch {
        // ignore backend content load failures for passive selection
      }
    })()

    return () => {
      cancelled = true
    }
  }, [activeLibraryFile, activeLibraryFileId, updateParsedFile])

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
    return files
      .filter((file) => (file.folderId || ROOT_FOLDER_ID) === currentFolderId)
      .sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0))
  }, [currentFolderId, files])

  const visibleLibraryFiles = useMemo(() => {
    return libraryFiles
      .filter((file) => (file.folderId || ROOT_FOLDER_ID) === currentFolderId)
      .sort((a, b) => Date.parse(b.parsedAt) - Date.parse(a.parsedAt))
  }, [currentFolderId, libraryFiles])

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
      const status = (file.status || 'parsed') as FileStatus
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
    activePdfQuality,
    activeQualityGate,
    activeRun,
    currentFolderId,
    folderPathById,
    isPdf,
    tocEnabled,
    visibleLibraryOnlyFiles,
    visibleQueueFiles,
  }
}
