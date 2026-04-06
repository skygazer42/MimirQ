'use client'

import { useCallback, type ChangeEvent, type Dispatch, type RefObject, type SetStateAction } from 'react'

import { toast } from 'sonner'

import { documentApi, parsingApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { deleteDocContentFromCache, deleteDocSourceFromCache, getDocContentFromCache, getDocSourceFromCache, saveDocSourceToCache } from '@/lib/doc-content-cache'
import { getParserLabel } from '@/lib/parser-options'
import { resolveParserBackendForFilename } from '@/lib/parser-compat'
import { restoreParsingRunFromMarkdown } from '@/lib/parsing-run-restore'
import { generateRequestId } from '@/lib/request-id'
import { detachPromise } from '@/lib/utils'
import { extractZipFiles, isZipFile } from '@/lib/zip'
import { ROOT_FOLDER_ID, type FolderNode, type ParsedFileData } from '@/store/use-parsed-files-store'
import { ZIP_ALLOWED_EXTENSIONS } from '@/lib/upload-extensions'
import { type FileStatus } from '@/components/ui/file-queue-item'

import type { ParseRun, ParsedFile } from './parsing-types'

type RebindTarget = {
  libraryId: string
  autoParse: boolean
}

type MutableRef<T> = {
  current: T
}

const normalizeBackendCandidate = (value: unknown): string =>
  typeof value === 'string' && value.trim() ? value.trim() : ''

type UseParsingLibraryActionsOptions = {
  activeFolderId: string | null
  countMarkdownHeadings: (markdown: string) => number
  createFolder: (name: string, parentId?: string) => string
  fileInputRef: RefObject<HTMLInputElement | null>
  filesRef: MutableRef<ParsedFile[]>
  folderInputRef: RefObject<HTMLInputElement | null>
  folders: FolderNode[]
  libraryFiles: ParsedFileData[]
  mapBackendStatusToLibraryStatus: (status?: string) => FileStatus
  parserBackend: string
  rebindInputRef: RefObject<HTMLInputElement | null>
  rebindTargetRef: MutableRef<RebindTarget | null>
  setActiveBlockId: Dispatch<SetStateAction<string | null>>
  setActiveFileId: Dispatch<SetStateAction<string | null>>
  setActiveFolderId: (folderId: string) => void
  setActiveLibraryFileId: Dispatch<SetStateAction<string | null>>
  setActiveLibrarySourceStatus: Dispatch<SetStateAction<'unknown' | 'available' | 'missing'>>
  setAutoParseFileId: Dispatch<SetStateAction<string | null>>
  setFiles: Dispatch<SetStateAction<ParsedFile[]>>
  setHoveredBlockId: Dispatch<SetStateAction<string | null>>
  setRightPanelMode: Dispatch<SetStateAction<'blocks' | 'markdown'>>
  updateParsedFile: (id: string, updates: Partial<Omit<ParsedFileData, 'id'>>) => void
  uploadTargetFolderIdRef: MutableRef<string | null>
  upsertParsedFile: (file: ParsedFileData) => void
}

export function useParsingLibraryActions({
  activeFolderId,
  countMarkdownHeadings,
  createFolder,
  fileInputRef,
  filesRef,
  folderInputRef,
  folders,
  libraryFiles,
  mapBackendStatusToLibraryStatus,
  parserBackend,
  rebindInputRef,
  rebindTargetRef,
  setActiveBlockId,
  setActiveFileId,
  setActiveFolderId,
  setActiveLibraryFileId,
  setActiveLibrarySourceStatus,
  setAutoParseFileId,
  setFiles,
  setHoveredBlockId,
  setRightPanelMode,
  updateParsedFile,
  uploadTargetFolderIdRef,
  upsertParsedFile,
}: Readonly<UseParsingLibraryActionsOptions>) {
  const generateId = useCallback(() => generateRequestId(), [])

  const requestUploadToFolder = useCallback(
    (folderId: string) => {
      const targetId = folderId || ROOT_FOLDER_ID
      uploadTargetFolderIdRef.current = targetId
      setActiveFolderId(targetId)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
        fileInputRef.current.click()
      }
    },
    [fileInputRef, setActiveFolderId, uploadTargetFolderIdRef]
  )

  const requestUploadFolder = useCallback(
    (folderId: string) => {
      const targetId = folderId || ROOT_FOLDER_ID
      uploadTargetFolderIdRef.current = targetId
      setActiveFolderId(targetId)
      if (folderInputRef.current) {
        folderInputRef.current.value = ''
        folderInputRef.current.click()
      }
    },
    [folderInputRef, setActiveFolderId, uploadTargetFolderIdRef]
  )

  const requestRebindForLibraryFile = useCallback(
    (libraryId: string, autoParse: boolean) => {
      const id = (libraryId || '').trim()
      if (!id) return
      rebindTargetRef.current = { libraryId: id, autoParse }
      if (rebindInputRef.current) {
        rebindInputRef.current.value = ''
        rebindInputRef.current.click()
      }
    },
    [rebindInputRef, rebindTargetRef]
  )

  const mountLibraryFileToQueue = useCallback(
    async (
      libraryId: string,
      sourceFile: File,
      options: { autoParse?: boolean; select?: boolean } = {}
    ) => {
      const id = (libraryId || '').trim()
      if (!id || !sourceFile) return null

      const libEntry = libraryFiles.find((file) => file.id === id) || null
      if (!libEntry) {
        toast.error('文档库条目不存在，无法恢复/重新绑定')
        return null
      }

      const preferredBackend = libEntry.parserBackend || parserBackend
      const resolved = resolveParserBackendForFilename(sourceFile.name, preferredBackend)
      const backend = resolved.backend
      const label = getParserLabel(backend)
      const folderId = libEntry.folderId || ROOT_FOLDER_ID
      const parsedAtTs = Date.parse(libEntry.parsedAt || '')
      const createdAt = Number.isFinite(parsedAtTs) ? parsedAtTs : Date.now()
      const queueId = generateId()
      const autoParse = Boolean(options.autoParse)
      const select = options.select ?? true
      const restoredDurationSec =
        !autoParse && Number.isFinite(Number(libEntry.durationSec)) ? Number(libEntry.durationSec) : undefined

      const libStatus = (libEntry.status || 'parsed') as FileStatus

      let status: FileStatus
      let errorMessage: string | undefined
      let markdownContent: string | null = null
      let runs: ParseRun[] | undefined
      let activeRunId: string | undefined
      let stats: ParsedFile['stats'] | undefined
      let blocks: ParseRun['blocks'] = []

      if (autoParse) {
        status = 'pending'
        errorMessage = undefined
        updateParsedFile(id, {
          filename: sourceFile.name,
          fileType: sourceFile.name.split('.').pop()?.toLowerCase() || '',
          fileSize: sourceFile.size,
          folderId,
          status: 'pending',
          error: undefined,
          parser: label,
          parserBackend: backend,
        })
      } else if (libStatus === 'parsed') {
        try {
          const cached = await getDocContentFromCache(id)
          const raw = (cached?.originalMarkdownContent || cached?.markdownContent || libEntry.markdownContent || '').trim()
          if (raw) {
            const restored = restoreParsingRunFromMarkdown({
              rawMarkdown: raw,
              cleanedMarkdown: (cached?.markdownContent || libEntry.markdownContent || '').trim(),
            })
            markdownContent = restored?.cleanedMarkdown || null
            blocks = restored?.blocks || []
            const runId = `restored-${Date.now()}`
            runs = [
              {
                id: runId,
                parserBackend: backend,
                parserLabel: label,
                rawMarkdown: raw,
                cleanedMarkdown: markdownContent || '',
                blocks,
                createdAt: Date.now(),
              },
            ]
            activeRunId = runId
            stats = {
              charCount: markdownContent.length,
              lineCount: markdownContent.split('\n').length,
              headingCount: countMarkdownHeadings(markdownContent),
              tableCount:
                (markdownContent.match(/\|.*\|/g) || []).length > 0
                  ? (markdownContent.match(/^\|/gm) || []).length / 2
                  : 0,
              imageCount: (markdownContent.match(/!\[.*?\]\(.*?\)/g) || []).length,
              blockCount: blocks.length,
            }
          }
        } catch {
          // ignore cache restore failures and fall back to pending state
        }
        status = markdownContent ? 'parsed' : 'pending'
      } else if (libStatus === 'error') {
        status = 'error'
        errorMessage = (libEntry.error || '').trim() || '解析失败'
      } else if (libStatus === 'parsing') {
        status = 'error'
        errorMessage = '上次解析被中断，请重试'
        updateParsedFile(id, { status: 'error', error: errorMessage })
      } else {
        status = 'pending'
      }

      const queueItem: ParsedFile = {
        id: queueId,
        file: sourceFile,
        folderId,
        name: sourceFile.name,
        size: sourceFile.size,
        status,
        duration: restoredDurationSec,
        markdownContent,
        error: errorMessage,
        parserBackend: backend,
        parserLabel: label,
        libraryId: id,
        createdAt,
        runs,
        activeRunId,
        stats,
      }

      setFiles((prev) => [...prev.filter((file) => file.libraryId !== id), queueItem])
      if (select) {
        setActiveFileId(queueId)
        setActiveLibraryFileId(null)
        setActiveBlockId(null)
        setHoveredBlockId(null)
        setRightPanelMode(blocks.length ? 'blocks' : 'markdown')
      }

      if (autoParse) setAutoParseFileId(queueId)
      return queueId
    },
    [
      countMarkdownHeadings,
      generateId,
      libraryFiles,
      parserBackend,
      setActiveBlockId,
      setActiveFileId,
      setActiveLibraryFileId,
      setAutoParseFileId,
      setFiles,
      setHoveredBlockId,
      setRightPanelMode,
      updateParsedFile,
    ]
  )

  const handleRebindFileSelect = useCallback(
    async (event: ChangeEvent<HTMLInputElement>) => {
      const target = rebindTargetRef.current
      rebindTargetRef.current = null

      const selectedFile = event.target.files?.[0] || null
      event.target.value = ''

      if (!target?.libraryId || !selectedFile) return

      try {
        await saveDocSourceToCache({ id: target.libraryId, file: selectedFile })
        setActiveLibrarySourceStatus('available')
      } catch (err) {
        console.warn('Failed to cache source file:', err)
        toast.warning('源文件本地缓存失败：刷新后需要预览时将从服务器重新下载')
      }

      detachPromise(mountLibraryFileToQueue(target.libraryId, selectedFile, { autoParse: target.autoParse }))
    },
    [mountLibraryFileToQueue, rebindTargetRef, setActiveLibrarySourceStatus]
  )

  const restoreLibraryFileFromCache = useCallback(
    async (libraryId: string, autoParse: boolean) => {
      const id = (libraryId || '').trim()
      if (!id) return

      const existing = filesRef.current.find((file) => file.libraryId === id) || null
      if (existing) {
        setActiveFileId(existing.id)
        setActiveLibraryFileId(null)
        if (autoParse) setAutoParseFileId(existing.id)
        return
      }

      try {
        const nameFromLibrary = libraryFiles.find((file) => file.id === id)?.filename || 'document'
        const cached = await getDocSourceFromCache(id).catch(() => null)
        if (cached?.blob) {
          const file = new File([cached.blob], cached.filename || nameFromLibrary, {
            type: cached.mimeType || cached.blob.type || 'application/octet-stream',
            lastModified: cached.lastModified || Date.now(),
          })
          setActiveLibrarySourceStatus('available')
          detachPromise(mountLibraryFileToQueue(id, file, { autoParse }))
          return
        }

        const blob = await documentApi.download(id, { inline: true })
        const file = new File([blob], nameFromLibrary, {
          type: blob.type || 'application/octet-stream',
          lastModified: Date.now(),
        })
        setActiveLibrarySourceStatus('available')
        detachPromise(mountLibraryFileToQueue(id, file, { autoParse }))
      } catch (err) {
        console.warn('Failed to restore source file:', err)
        setActiveLibrarySourceStatus('missing')
        toast.error('从服务器下载源文件失败，请稍后重试')
      }
    },
    [
      filesRef,
      libraryFiles,
      mountLibraryFileToQueue,
      setActiveFileId,
      setActiveLibraryFileId,
      setActiveLibrarySourceStatus,
      setAutoParseFileId,
    ]
  )

  const addFiles = useCallback(
    async (incomingFiles: File[], baseFolderIdOverride?: string) => {
      const baseFolderId = baseFolderIdOverride || activeFolderId || ROOT_FOLDER_ID
      const now = Date.now()

      const folderIdByKey = new Map<string, string>()
      for (const folder of folders) {
        folderIdByKey.set(`${folder.parentId || ROOT_FOLDER_ID}::${folder.name}`, folder.id)
      }

      const getOrCreateFolder = (parentId: string, name: string) => {
        const trimmed = name.trim()
        if (!trimmed) return parentId

        const key = `${parentId}::${trimmed}`
        const cached = folderIdByKey.get(key)
        if (cached) return cached

        const existing = folders.find((folder) => (folder.parentId || ROOT_FOLDER_ID) === parentId && folder.name === trimmed)
        if (existing) {
          folderIdByKey.set(key, existing.id)
          return existing.id
        }

        const newId = createFolder(trimmed, parentId)
        folderIdByKey.set(key, newId)
        return newId
      }

      const queued: ParsedFile[] = []
      let skipped = 0
      let added = 0

      for (const file of incomingFiles) {
        const relativePath = (file as File & { webkitRelativePath?: string }).webkitRelativePath || ''
        if (relativePath) {
          const parts = relativePath.split('/')
          const filename = parts.pop()
          if (!filename) continue

          const ext = filename.split('.').pop()?.toLowerCase() || ''
          if (!ZIP_ALLOWED_EXTENSIONS.has(ext)) {
            skipped += 1
            continue
          }

          let currentFolderId = baseFolderId
          for (const segment of parts) {
            currentFolderId = getOrCreateFolder(currentFolderId, segment)
          }

          const resolvedParser = resolveParserBackendForFilename(filename, parserBackend)
          queued.push({
            id: generateId(),
            file,
            folderId: currentFolderId,
            name: filename,
            sourcePath: relativePath,
            size: file.size,
            status: 'pending',
            markdownContent: null,
            error: undefined,
            parserBackend: resolvedParser.backend,
            parserLabel: getParserLabel(resolvedParser.backend),
            createdAt: now,
          })
          added += 1
          continue
        }

        if (isZipFile(file)) {
          let extractedCount = 0
          let addedInZip = 0
          let skippedInZip = 0

          try {
            const extracted = await extractZipFiles(file)
            extractedCount = extracted.length

            for (const item of extracted) {
              const parts = item.path.split('/').filter(Boolean)
              const filename = parts.pop()
              if (!filename) continue

              const ext = filename.split('.').pop()?.toLowerCase() || ''
              if (!ZIP_ALLOWED_EXTENSIONS.has(ext)) {
                skipped += 1
                skippedInZip += 1
                continue
              }

              let folderId = baseFolderId
              for (const segment of parts) {
                folderId = getOrCreateFolder(folderId, segment)
              }

              const resolvedParser = resolveParserBackendForFilename(filename, parserBackend)
              queued.push({
                id: generateId(),
                file: item.file,
                folderId,
                name: item.file.name,
                sourcePath: item.path,
                size: item.file.size,
                status: 'pending',
                markdownContent: null,
                error: undefined,
                parserBackend: resolvedParser.backend,
                parserLabel: getParserLabel(resolvedParser.backend),
                createdAt: now,
              })
              added += 1
              addedInZip += 1
            }
          } catch (err) {
            console.error('Failed to extract zip:', err)
            toast.error(`ZIP 解压失败：${file.name}`)
          }

          if (addedInZip === 0) {
            toast.warning(
              extractedCount === 0 ? `ZIP 中未找到文件：${file.name}` : `ZIP 中没有可解析文件：${file.name}`
            )
          } else {
            toast.success(
              skippedInZip > 0
                ? `已从 ZIP 添加 ${addedInZip} 个文件（跳过 ${skippedInZip} 个）`
                : `已从 ZIP 添加 ${addedInZip} 个文件`
            )
          }
          continue
        }

        const ext = file.name.split('.').pop()?.toLowerCase() || ''
        if (!ZIP_ALLOWED_EXTENSIONS.has(ext)) {
          skipped += 1
          continue
        }

        const resolvedParser = resolveParserBackendForFilename(file.name, parserBackend)
        queued.push({
          id: generateId(),
          file,
          folderId: baseFolderId,
          name: file.name,
          size: file.size,
          status: 'pending',
          markdownContent: null,
          error: undefined,
          parserBackend: resolvedParser.backend,
          parserLabel: getParserLabel(resolvedParser.backend),
          createdAt: now,
        })
        added += 1
      }

      if (queued.length === 0) {
        if (skipped > 0) toast.warning(`已跳过 ${skipped} 个不支持的文件`)
        return
      }

      const queuedWithLibrary: ParsedFile[] = []
      let uploadFailed = 0

      for (const queuedFile of queued) {
        try {
          const doc = await parsingApi.upload(queuedFile.file, { parser_backend: queuedFile.parserBackend })
          const libId = String(doc.id || '').trim()
          if (!libId) throw new Error('Missing document id from backend')

          const metadata = doc.metadata as Record<string, unknown> | undefined
          const requestedBackend =
            normalizeBackendCandidate(metadata?.parser_backend_requested) ||
            queuedFile.parserBackend ||
            'auto'

          upsertParsedFile({
            id: libId,
            filename: doc.filename || queuedFile.name,
            fileType: doc.file_type || queuedFile.name.split('.').pop()?.toLowerCase() || '',
            fileSize: Number(doc.file_size || queuedFile.size),
            markdownContent: '',
            originalMarkdownContent: '',
            parsedAt: String(doc.updated_at || doc.created_at || new Date().toISOString()),
            parser: getParserLabel(requestedBackend),
            parserBackend: requestedBackend,
            folderId: queuedFile.folderId,
            status: mapBackendStatusToLibraryStatus(doc.status),
            error: doc.error_message || undefined,
          })

          queuedWithLibrary.push({ ...queuedFile, libraryId: libId })
        } catch (err: unknown) {
          uploadFailed += 1
          queuedWithLibrary.push({
            ...queuedFile,
            status: 'error',
            error: formatApiError(err, '上传失败'),
          })
        }
      }

      setFiles((prev) => [...prev, ...queuedWithLibrary])
      setActiveFileId((prev) => prev ?? queuedWithLibrary[0].id)

      if (added > 0) toast.success(`已加入队列：${added} 个文件`)
      if (uploadFailed > 0) toast.warning(`有 ${uploadFailed} 个文件上传失败（可稍后重试）`)
      if (skipped > 0) toast.warning(`已跳过 ${skipped} 个不支持的文件`)
    },
    [
      activeFolderId,
      createFolder,
      folders,
      generateId,
      mapBackendStatusToLibraryStatus,
      parserBackend,
      setActiveFileId,
      setFiles,
      upsertParsedFile,
    ]
  )

  const removeLibraryCaches = useCallback((fileId: string) => {
    detachPromise(deleteDocContentFromCache(fileId))
    detachPromise(deleteDocSourceFromCache(fileId))
  }, [])

  return {
    addFiles,
    handleRebindFileSelect,
    mountLibraryFileToQueue,
    removeLibraryCaches,
    requestRebindForLibraryFile,
    requestUploadFolder,
    requestUploadToFolder,
    restoreLibraryFileFromCache,
  }
}
