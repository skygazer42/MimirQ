'use client'

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  type ChangeEvent,
  type Dispatch,
  type RefObject,
  type SetStateAction,
} from 'react'

import { toast } from 'sonner'
import { useQueryClient } from '@tanstack/react-query'

import { documentApi } from '@/lib/api/documents'
import { parsingApi } from '@/lib/api/parsing'
import { extractHttpStatus, formatApiError } from '@/lib/api-errors'
import { getAuthCacheScope, getAuthSessionRevision } from '@/lib/auth-storage'
import { reportClientError, reportClientWarning } from '@/lib/client-logging'
import { getDocSourceFromCache, saveDocSourceToCache } from '@/lib/doc-content-cache'
import { getParserLabel } from '@/lib/parser-options'
import { resolveParserBackendForFilename } from '@/lib/parser-compat'
import { restoreParsingRunFromMarkdown } from '@/lib/parsing-run-restore'
import { generateRequestId } from '@/lib/request-id'
import { queryKeys } from '@/lib/query-keys'
import { extractZipFiles, isZipFile } from '@/lib/zip'
import { ROOT_FOLDER_ID, useParsedFiles, type ParsedFileData } from '@/store/use-parsed-files-store'
import { ZIP_ALLOWED_EXTENSIONS } from '@/lib/upload-extensions'

import type { FileStatus, ParseRun, ParsedFile } from './parsing-types'
import { loadParsingLibraryContent } from './parsing-library-content'
import {
  buildParsingStatistics,
  mapBackendStatusToLibraryStatus,
  normalizeParsingBackendCandidate,
} from './parsing-page-utils'

type RebindTarget = {
  libraryId: string
  autoParse: boolean
}

type UseParsingLibraryActionsOptions = {
  activeFolderId: string
  activeFileId: string | null
  activeLibraryFileId: string | null
  createFolder: (name: string, parentId?: string) => string
  fileInputRef: RefObject<HTMLInputElement | null>
  filesRef: RefObject<ParsedFile[]>
  folderInputRef: RefObject<HTMLInputElement | null>
  isLibraryLoaded: boolean
  libraryFiles: ParsedFileData[]
  parserBackend: string
  selectedDatasetId: string | null
  rebindInputRef: RefObject<HTMLInputElement | null>
  rebindTargetRef: RefObject<RebindTarget | null>
  removeParsedFile: (id: string) => void
  setActiveBlockId: Dispatch<SetStateAction<string | null>>
  setActiveFileId: Dispatch<SetStateAction<string | null>>
  setActiveFolderId: (folderId: string) => void
  setActiveLibraryFileId: Dispatch<SetStateAction<string | null>>
  setAutoParseFileId: Dispatch<SetStateAction<string | null>>
  setFiles: Dispatch<SetStateAction<ParsedFile[]>>
  setHoveredBlockId: Dispatch<SetStateAction<string | null>>
  setIsQueueRehydrating: Dispatch<SetStateAction<boolean>>
  setRightPanelMode: Dispatch<SetStateAction<'blocks' | 'markdown'>>
  updateParsedFile: (id: string, updates: Partial<Omit<ParsedFileData, 'id'>>) => Promise<void>
  uploadTargetFolderIdRef: RefObject<string | null>
  upsertParsedFile: (file: ParsedFileData) => void
}

export function useParsingLibraryActions({
  activeFolderId,
  activeFileId,
  activeLibraryFileId,
  createFolder,
  fileInputRef,
  filesRef,
  folderInputRef,
  isLibraryLoaded,
  libraryFiles,
  parserBackend,
  selectedDatasetId,
  rebindInputRef,
  rebindTargetRef,
  removeParsedFile,
  setActiveBlockId,
  setActiveFileId,
  setActiveFolderId,
  setActiveLibraryFileId,
  setAutoParseFileId,
  setFiles,
  setHoveredBlockId,
  setIsQueueRehydrating,
  setRightPanelMode,
  updateParsedFile,
  uploadTargetFolderIdRef,
  upsertParsedFile,
}: Readonly<UseParsingLibraryActionsOptions>) {
  const queryClient = useQueryClient()
  const mountedRef = useRef(false)
  const sourceControllersRef = useRef(new Map<string, AbortController>())
  const attemptedSourceIdsRef = useRef(new Set<string>())
  const selectionRef = useRef({ activeFileId, activeLibraryFileId })
  useEffect(() => {
    selectionRef.current = { activeFileId, activeLibraryFileId }
  }, [activeFileId, activeLibraryFileId])
  useEffect(() => {
    const controllers = sourceControllersRef.current
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      for (const controller of controllers.values()) controller.abort()
      controllers.clear()
    }
  }, [])

  const beginSourceRequest = useCallback((libraryId: string) => {
    sourceControllersRef.current.get(libraryId)?.abort()
    const controller = new AbortController()
    sourceControllersRef.current.set(libraryId, controller)
    return controller
  }, [])

  const requestUploadToFolder = useCallback(
    (folderId: string) => {
      uploadTargetFolderIdRef.current = folderId
      setActiveFolderId(folderId)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
        fileInputRef.current.click()
      }
    },
    [fileInputRef, setActiveFolderId, uploadTargetFolderIdRef],
  )

  const requestUploadFolder = useCallback(
    (folderId: string) => {
      uploadTargetFolderIdRef.current = folderId
      setActiveFolderId(folderId)
      if (folderInputRef.current) {
        folderInputRef.current.value = ''
        folderInputRef.current.click()
      }
    },
    [folderInputRef, setActiveFolderId, uploadTargetFolderIdRef],
  )

  const requestRebindForLibraryFile = useCallback(
    (libraryId: string, autoParse: boolean) => {
      rebindTargetRef.current = { libraryId, autoParse }
      if (rebindInputRef.current) {
        rebindInputRef.current.value = ''
        rebindInputRef.current.click()
      }
    },
    [rebindInputRef, rebindTargetRef],
  )

  const mountLibraryFileToQueue = useCallback(
    async (
      libraryId: string,
      sourceFile: File,
      options: { autoParse?: boolean; select?: boolean; forceRefresh?: boolean; controller?: AbortController } = {},
    ) => {
      const controller = options.controller ?? beginSourceRequest(libraryId)
      const scope = getAuthCacheScope()
      const revision = getAuthSessionRevision()
      const isCurrent = () =>
        mountedRef.current &&
        !controller.signal.aborted &&
        sourceControllersRef.current.get(libraryId) === controller &&
        scope === getAuthCacheScope() &&
        revision === getAuthSessionRevision()
      try {
        if (!isCurrent()) return null
        const id = libraryId
        const selection = selectionRef.current
        const libEntry = useParsedFiles.getState().files.find((file) => file.id === id)
        if (!libEntry) {
          toast.error('文档库条目不存在，无法恢复/重新绑定')
          return null
        }

        const preferredBackend = libEntry.parserBackend ?? parserBackend
        const filename = libEntry.source === undefined ? sourceFile.name : libEntry.filename
        const resolved = resolveParserBackendForFilename(filename, preferredBackend)
        let backend = resolved.backend
        let label = getParserLabel(backend)
        const createdAt = Date.parse(libEntry.parsedAt)
        const queueId = generateRequestId()
        const autoParse = libEntry.source === 'knowledge_base' ? false : (options.autoParse ?? false)
        const select = options.select ?? true
        let restoredDurationSec = autoParse ? undefined : libEntry.durationSec

        const result = await loadParsingLibraryContent(libEntry, {
          refresh: options.forceRefresh,
          signal: controller.signal,
        })
        if (!isCurrent()) return null
        const current = useParsedFiles.getState().files.find((file) => file.id === id)
        if (
          current === undefined ||
          current.source !== libEntry.source ||
          current.parsedAt !== libEntry.parsedAt ||
          current.status !== libEntry.status
        )
          return null
        const contentUnchanged =
          current.markdownContent === libEntry.markdownContent &&
          current.originalMarkdownContent === libEntry.originalMarkdownContent
        const matchesSavedContent =
          result.content !== undefined &&
          current.markdownContent === result.content.markdownContent &&
          current.originalMarkdownContent === result.content.originalMarkdownContent
        if (!contentUnchanged && !matchesSavedContent) return null
        let status: FileStatus = autoParse ? 'pending' : result.status
        let errorMessage = autoParse ? undefined : result.error
        if (!autoParse && status === 'parsing' && libEntry.source !== 'knowledge_base') {
          status = 'error'
          errorMessage = '上次解析被中断，请重试'
        }
        if (!autoParse) await updateParsedFile(id, { ...result.content, status, error: errorMessage })

        let markdownContent: string | null = null
        let runs: ParseRun[] | undefined
        let activeRunId: string | undefined
        let stats: ParsedFile['stats'] | undefined
        let restoredElements = libEntry.elements

        const content = result.content
        if (content !== undefined) {
          backend = content.parserBackend ?? backend
          label = getParserLabel(backend)
          restoredDurationSec = content.durationSec
          restoredElements = content.elements
          const restored = restoreParsingRunFromMarkdown({
            rawMarkdown: content.originalMarkdownContent,
            cleanedMarkdown: content.markdownContent,
          })
          markdownContent = restored.cleanedMarkdown
          const blocks = content.contentEdited === true ? [] : restored.blocks
          stats = buildParsingStatistics(markdownContent, blocks.length, content.stats)
          activeRunId = generateRequestId()
          runs = [
            {
              id: activeRunId,
              parserBackend: backend,
              parserLabel: label,
              rawMarkdown: content.originalMarkdownContent,
              cleanedMarkdown: markdownContent,
              blocks,
              elements: restoredElements,
              stats,
              durationSec: restoredDurationSec,
              pdfQuality: content.pdfQuality,
              qualityGate: content.qualityGate,
              contentEdited: content.contentEdited,
              createdAt: Date.now(),
            },
          ]
        }

        if (!isCurrent()) return null
        const currentEntry = useParsedFiles.getState().files.find((file) => file.id === id)
        if (currentEntry === undefined) return null

        const queueItem: ParsedFile = {
          id: queueId,
          file: sourceFile,
          folderId: currentEntry.folderId ?? ROOT_FOLDER_ID,
          name: filename,
          size: libEntry.source === undefined ? sourceFile.size : libEntry.fileSize,
          status,
          duration: restoredDurationSec,
          markdownContent,
          contentEdited: content?.contentEdited,
          error: errorMessage,
          parserBackend: backend,
          parserLabel: label,
          datasetId: libEntry.datasetId,
          datasetName: libEntry.datasetName,
          sourcePath: libEntry.sourcePath ?? libEntry.datasetName ?? undefined,
          libraryId: id,
          librarySource: libEntry.source,
          governanceStatus: currentEntry.governanceStatus,
          createdAt,
          runs,
          activeRunId,
          savedRunId: libEntry.source === 'parsing_workspace' ? activeRunId : undefined,
          stats,
          elements: restoredElements,
        }

        setFiles((prev) => [...prev.filter((file) => file.libraryId !== id), queueItem])
        if (select && selectionRef.current === selection) {
          setActiveFileId(queueId)
          setActiveLibraryFileId(null)
          setActiveBlockId(null)
          setHoveredBlockId(null)
          setRightPanelMode('markdown')
        }

        if (autoParse) setAutoParseFileId(queueId)
        return queueId
      } finally {
        if (options.controller === undefined && sourceControllersRef.current.get(libraryId) === controller)
          sourceControllersRef.current.delete(libraryId)
      }
    },
    [
      beginSourceRequest,
      parserBackend,
      setActiveBlockId,
      setActiveFileId,
      setActiveLibraryFileId,
      setAutoParseFileId,
      setFiles,
      setHoveredBlockId,
      setRightPanelMode,
      updateParsedFile,
    ],
  )

  // Content writes during restoration do not change the catalog of source targets.
  const sourceCatalog = useMemo(
    () =>
      JSON.stringify(
        libraryFiles.map((file) => [
          file.id,
          file.folderId,
          file.source,
          file.datasetId,
          file.status !== 'parsed' && file.status !== undefined,
        ]),
      ),
    [libraryFiles],
  )
  useEffect(() => {
    if (!isLibraryLoaded) return
    const controllers = sourceControllersRef.current
    const attemptedIds = attemptedSourceIdsRef.current
    const queuedIds = new Set(filesRef.current.map((file) => file.libraryId))
    const candidates = useParsedFiles
      .getState()
      .files.filter(
        (file) =>
          file.source !== 'knowledge_base' &&
          (file.status === 'pending' || file.status === 'error' || file.status === 'parsing') &&
          !queuedIds.has(file.id) &&
          !attemptedIds.has(file.id) &&
          (selectedDatasetId === null
            ? (file.folderId ?? ROOT_FOLDER_ID) === activeFolderId
            : file.datasetId === selectedDatasetId),
      )
    if (candidates.length === 0) {
      setIsQueueRehydrating(false)
      return
    }
    let cancelled = false
    let activeSourceId: string | undefined
    let activeController: AbortController | undefined
    const scope = getAuthCacheScope()
    const revision = getAuthSessionRevision()
    const isCurrent = () => !cancelled && scope === getAuthCacheScope() && revision === getAuthSessionRevision()
    setIsQueueRehydrating(true)
    async function restoreSources() {
      let missing = 0
      for (const entry of candidates) {
        if (!isCurrent()) return
        if (controllers.has(entry.id) || filesRef.current.some((file) => file.libraryId === entry.id)) continue
        activeSourceId = entry.id
        attemptedIds.add(entry.id)
        const controller = beginSourceRequest(entry.id)
        activeController = controller
        const ownsRequest = () =>
          isCurrent() &&
          !controller.signal.aborted &&
          controllers.get(entry.id) === controller &&
          useParsedFiles.getState().files.some((file) => file.id === entry.id)
        try {
          const cached = await getDocSourceFromCache(entry.id, scope)
          if (!ownsRequest()) continue
          if (cached === null) {
            missing += 1
            continue
          }
          const file = new File([cached.blob], cached.filename, {
            type: cached.mimeType,
            lastModified: cached.lastModified,
          })
          await mountLibraryFileToQueue(entry.id, file, { select: false, controller })
        } catch (error) {
          if (!ownsRequest()) continue
          reportClientWarning('Failed to restore a cached parsing source', error)
          toast.error(`${entry.filename}：${formatApiError(error, '读取原文件失败')}`)
        } finally {
          if (controllers.get(entry.id) === controller) controllers.delete(entry.id)
          activeSourceId = undefined
          activeController = undefined
        }
      }
      if (isCurrent() && missing > 0) toast.warning(`有 ${missing} 个文档未缓存原文件，打开时可重新关联或恢复`)
    }
    void restoreSources().finally(() => {
      if (isCurrent()) setIsQueueRehydrating(false)
    })
    return () => {
      cancelled = true
      activeController?.abort()
      if (activeSourceId !== undefined) {
        attemptedIds.delete(activeSourceId)
        if (controllers.get(activeSourceId) === activeController) controllers.delete(activeSourceId)
      }
    }
  }, [
    sourceCatalog,
    activeFolderId,
    selectedDatasetId,
    filesRef,
    isLibraryLoaded,
    beginSourceRequest,
    mountLibraryFileToQueue,
    setIsQueueRehydrating,
  ])

  const handleRebindFileSelect = useCallback(
    async (event: ChangeEvent<HTMLInputElement>) => {
      const target = rebindTargetRef.current
      const selection = selectionRef.current
      rebindTargetRef.current = null

      const scope = getAuthCacheScope()
      const revision = getAuthSessionRevision()
      const selectedFile = event.target.files?.[0]
      event.target.value = ''
      if (target === null || selectedFile === undefined) return
      const controller = beginSourceRequest(target.libraryId)
      const isCurrent = () =>
        mountedRef.current &&
        !controller.signal.aborted &&
        sourceControllersRef.current.get(target.libraryId) === controller &&
        useParsedFiles.getState().files.some((file) => file.id === target.libraryId) &&
        scope === getAuthCacheScope() &&
        revision === getAuthSessionRevision()
      try {
        if (!isCurrent()) return

        try {
          await saveDocSourceToCache({ id: target.libraryId, file: selectedFile }, scope, controller.signal)
          if (!isCurrent()) return
          await queryClient.cancelQueries({ queryKey: queryKeys.parsing.librarySource(target.libraryId) })
          if (!isCurrent()) return
          queryClient.setQueryData(queryKeys.parsing.librarySource(target.libraryId), 'available')
        } catch (err) {
          if (!isCurrent()) return
          reportClientWarning('Failed to cache parsing source file', err)
          toast.warning('原文件缓存失败，本次仍可预览；刷新后需要重新关联')
        }

        try {
          await mountLibraryFileToQueue(target.libraryId, selectedFile, {
            autoParse: target.autoParse,
            select: selectionRef.current === selection,
            controller,
          })
        } catch (error) {
          if (isCurrent()) toast.error(formatApiError(error, '恢复解析文档失败'))
        }
      } finally {
        if (sourceControllersRef.current.get(target.libraryId) === controller)
          sourceControllersRef.current.delete(target.libraryId)
      }
    },
    [beginSourceRequest, mountLibraryFileToQueue, queryClient, rebindTargetRef],
  )

  const restoreLibraryFileFromCache = useCallback(
    async (libraryId: string, autoParse: boolean) => {
      const id = libraryId
      const selection = selectionRef.current
      const scope = getAuthCacheScope()
      const revision = getAuthSessionRevision()
      const controller = beginSourceRequest(id)
      const isCurrent = () =>
        mountedRef.current &&
        !controller.signal.aborted &&
        sourceControllersRef.current.get(id) === controller &&
        useParsedFiles.getState().files.some((file) => file.id === id) &&
        scope === getAuthCacheScope() &&
        revision === getAuthSessionRevision()
      try {
        if (!isCurrent()) return
        const existing = filesRef.current.find((file) => file.libraryId === id)
        if (existing) {
          setActiveFileId(existing.id)
          setActiveLibraryFileId(null)
          if (autoParse) setAutoParseFileId(existing.id)
          return
        }

        try {
          const entry = useParsedFiles.getState().files.find((file) => file.id === id)
          if (entry === undefined) return
          setActiveFileId(null)
          setActiveLibraryFileId(id)
          const selectsTarget = () =>
            selectionRef.current === selection ||
            (selectionRef.current.activeFileId === null && selectionRef.current.activeLibraryFileId === id)
          const cached = await getDocSourceFromCache(id, scope)
          if (!isCurrent() || useParsedFiles.getState().files.find((file) => file.id === id)?.source !== entry.source)
            return
          if (cached !== null) {
            const file = new File([cached.blob], cached.filename, {
              type: cached.mimeType,
              lastModified: cached.lastModified,
            })
            await mountLibraryFileToQueue(id, file, {
              autoParse,
              select: selectsTarget(),
              controller,
            })
            return
          }

          if (entry.source === undefined) {
            await queryClient.cancelQueries({ queryKey: queryKeys.parsing.librarySource(id) })
            if (!isCurrent()) return
            queryClient.setQueryData(queryKeys.parsing.librarySource(id), 'missing')
            return
          }
          const blob = await documentApi
            .download(id, { inline: true }, { signal: controller.signal })
            .catch(async (error) => {
              if (isCurrent() && extractHttpStatus(error) === 404) {
                const queryKey = queryKeys.parsing.librarySource(id)
                await queryClient.cancelQueries({ queryKey })
                if (isCurrent()) queryClient.setQueryData(queryKey, 'missing')
              }
              throw error
            })
          if (!isCurrent() || useParsedFiles.getState().files.find((file) => file.id === id)?.source !== entry.source)
            return
          const file = new File([blob], entry.filename, {
            type: blob.type,
          })
          await mountLibraryFileToQueue(id, file, { autoParse, select: selectsTarget(), controller })
        } catch (err) {
          if (!isCurrent()) return
          reportClientWarning('Failed to restore parsing source file', err)
          toast.error(formatApiError(err, '恢复解析文档失败，请稍后重试'))
        }
      } finally {
        if (sourceControllersRef.current.get(id) === controller) sourceControllersRef.current.delete(id)
      }
    },
    [
      beginSourceRequest,
      filesRef,
      mountLibraryFileToQueue,
      queryClient,
      setActiveFileId,
      setActiveLibraryFileId,
      setAutoParseFileId,
    ],
  )

  const addFiles = useCallback(
    async (incomingFiles: File[], baseFolderIdOverride?: string) => {
      const selection = selectionRef.current
      const scope = getAuthCacheScope()
      const revision = getAuthSessionRevision()
      const isCurrent = () =>
        mountedRef.current && scope === getAuthCacheScope() && revision === getAuthSessionRevision()
      const baseFolderId = baseFolderIdOverride ?? activeFolderId
      const now = Date.now()
      const folderExists = (folderId: string) =>
        folderId === ROOT_FOLDER_ID || useParsedFiles.getState().folders.some((folder) => folder.id === folderId)
      if (!folderExists(baseFolderId)) {
        toast.error('目标文件夹已移除，请重新选择上传位置')
        return
      }

      const getOrCreateFolder = (parentId: string, name: string) => {
        const trimmed = name.trim()
        if (!trimmed) return parentId

        const existing = useParsedFiles
          .getState()
          .folders.find((folder) => folder.parentId === parentId && folder.name === trimmed)
        return existing === undefined ? createFolder(trimmed, parentId) : existing.id
      }

      const queued: ParsedFile[] = []
      let skipped = 0
      const enqueueFile = (file: File, folderId: string, sourcePath?: string) => {
        const resolvedParser = resolveParserBackendForFilename(file.name, parserBackend)
        queued.push({
          id: generateRequestId(),
          file,
          folderId,
          name: file.name,
          sourcePath,
          size: file.size,
          status: 'pending',
          markdownContent: null,
          parserBackend: resolvedParser.backend,
          parserLabel: getParserLabel(resolvedParser.backend),
          datasetId: selectedDatasetId,
          createdAt: now,
        })
      }

      for (const file of incomingFiles) {
        const relativePath = file.webkitRelativePath
        if (relativePath) {
          const parts = relativePath.split('/')
          const filename = parts.pop()
          if (!filename) continue

          const ext = filename.slice(filename.lastIndexOf('.') + 1).toLowerCase()
          if (!ZIP_ALLOWED_EXTENSIONS.has(ext)) {
            skipped += 1
            continue
          }

          let currentFolderId = baseFolderId
          for (const segment of parts) {
            currentFolderId = getOrCreateFolder(currentFolderId, segment)
          }

          enqueueFile(file, currentFolderId, relativePath)
          continue
        }

        if (isZipFile(file)) {
          let extractedCount = 0
          let addedInZip = 0

          try {
            const extracted = await extractZipFiles(file)
            if (!isCurrent()) return
            if (!folderExists(baseFolderId)) {
              toast.error('目标文件夹已移除，已取消本次添加')
              return
            }
            extractedCount = extracted.length

            for (const item of extracted) {
              const parts = item.path.split('/').filter(Boolean)
              const filename = parts.pop()
              if (!filename) continue

              const ext = filename.slice(filename.lastIndexOf('.') + 1).toLowerCase()
              if (!ZIP_ALLOWED_EXTENSIONS.has(ext)) {
                skipped += 1
                continue
              }

              let folderId = baseFolderId
              for (const segment of parts) {
                folderId = getOrCreateFolder(folderId, segment)
              }

              enqueueFile(item.file, folderId, item.path)
              addedInZip += 1
            }
          } catch (err) {
            if (!isCurrent()) return
            reportClientError('Failed to extract parsing ZIP upload', err)
            toast.error(`ZIP 解压失败：${file.name}`)
            continue
          }

          if (addedInZip === 0) {
            toast.warning(
              extractedCount === 0 ? `ZIP 中未找到文件：${file.name}` : `ZIP 中没有可解析文件：${file.name}`,
            )
          }
          continue
        }

        const ext = file.name.slice(file.name.lastIndexOf('.') + 1).toLowerCase()
        if (!ZIP_ALLOWED_EXTENSIONS.has(ext)) {
          skipped += 1
          continue
        }

        enqueueFile(file, baseFolderId)
      }

      if (queued.length === 0) {
        if (skipped > 0) toast.warning(`已跳过 ${skipped} 个不支持的文件`)
        return
      }

      const queuedWithLibrary: ParsedFile[] = []
      let uploadFailed = 0
      let cancelledUploads = 0

      for (const queuedFile of queued) {
        if (!folderExists(queuedFile.folderId)) {
          cancelledUploads += 1
          continue
        }
        let queueItem = queuedFile
        try {
          const doc = await parsingApi.upload(queuedFile.file, {
            parser_backend: queuedFile.parserBackend,
            dataset_id: selectedDatasetId,
          })
          if (!isCurrent()) return
          const libraryId = doc.id
          if (!folderExists(queuedFile.folderId)) {
            cancelledUploads += 1
            try {
              await parsingApi.delete(libraryId)
              if (!isCurrent()) return
              await queryClient.cancelQueries({ queryKey: ['parsing', 'library-snapshot'] })
              if (!isCurrent()) return
              removeParsedFile(libraryId)
              await queryClient.invalidateQueries({ queryKey: ['parsing', 'library-snapshot'] })
            } catch (error) {
              reportClientWarning('Failed to cancel an upload after its folder was removed', error)
              if (isCurrent()) {
                toast.error('目标文件夹已移除，服务器文档撤销失败，请在同步后的文档目录中检查')
                await queryClient.invalidateQueries({ queryKey: ['parsing', 'library-snapshot'] })
              }
            }
            continue
          }

          const metadata = doc.metadata
          const targetDatasetId =
            normalizeParsingBackendCandidate(metadata?.target_dataset_id) ?? queuedFile.datasetId ?? null
          const targetDatasetName = normalizeParsingBackendCandidate(metadata?.target_dataset_name) ?? null
          const requestedBackend =
            normalizeParsingBackendCandidate(metadata?.parser_backend_requested) ?? queuedFile.parserBackend
          queueItem = {
            ...queuedFile,
            libraryId,
            librarySource: 'parsing_workspace',
            datasetId: targetDatasetId,
            datasetName: targetDatasetName,
          }

          upsertParsedFile({
            id: libraryId,
            filename: doc.filename,
            fileType: doc.file_type,
            fileSize: doc.file_size,
            markdownContent: '',
            originalMarkdownContent: '',
            parsedAt: doc.updated_at,
            parser: getParserLabel(requestedBackend),
            parserBackend: requestedBackend,
            folderId: queuedFile.folderId,
            datasetId: targetDatasetId,
            datasetName: targetDatasetName,
            source: 'parsing_workspace',
            status: mapBackendStatusToLibraryStatus(doc.status),
            error: doc.error_message === null ? undefined : doc.error_message,
          })

          queuedWithLibrary.push(queueItem)
        } catch (err: unknown) {
          if (!isCurrent()) return
          uploadFailed += 1
          queuedWithLibrary.push({
            ...queueItem,
            status: 'error',
            error: formatApiError(err, '上传失败'),
          })
        }
      }

      if (!isCurrent()) return
      const currentById = new Map(useParsedFiles.getState().files.map((file) => [file.id, file]))
      const remaining = queuedWithLibrary
        .filter((file) => file.status === 'error' || (file.libraryId !== undefined && currentById.has(file.libraryId)))
        .map((file) => {
          const current = file.libraryId === undefined ? undefined : currentById.get(file.libraryId)
          return current === undefined ? file : { ...file, folderId: current.folderId ?? ROOT_FOLDER_ID }
        })
        .filter((file) => folderExists(file.folderId))
      setFiles((prev) => [...prev, ...remaining])
      if (remaining.length > 0 && selectionRef.current === selection) {
        setActiveFileId((prev) => prev ?? remaining[0].id)
      }

      const uploadedCount = remaining.filter((file) => file.status !== 'error').length
      if (uploadedCount > 0) {
        toast.success(
          selectedDatasetId
            ? `已添加到当前数据集解析区：${uploadedCount} 个文件`
            : `已添加到解析列表：${uploadedCount} 个文件`,
        )
      }
      if (uploadFailed > 0) toast.warning(`有 ${uploadFailed} 个文件未完成添加（可稍后重试）`)
      if (cancelledUploads > 0) toast.warning(`目标文件夹已移除，已取消添加 ${cancelledUploads} 个文件`)
      if (skipped > 0) toast.warning(`已跳过 ${skipped} 个不支持的文件`)
    },
    [
      activeFolderId,
      createFolder,
      queryClient,
      removeParsedFile,
      parserBackend,
      selectedDatasetId,
      setActiveFileId,
      setFiles,
      upsertParsedFile,
    ],
  )

  return {
    addFiles,
    handleRebindFileSelect,
    mountLibraryFileToQueue,
    requestRebindForLibraryFile,
    requestUploadFolder,
    requestUploadToFolder,
    restoreLibraryFileFromCache,
  }
}
