'use client'

import { useQueryClient } from '@tanstack/react-query'
import {
  useCallback,
  useEffect,
  useRef,
  type Dispatch,
  type DragEvent,
  type RefObject,
  type SetStateAction,
} from 'react'
import { useTranslations } from 'next-intl'

import { toast } from 'sonner'

import { documentApi } from '@/lib/api/documents'
import { parsingApi } from '@/lib/api/parsing'
import { formatApiError } from '@/lib/api-errors'
import { getAuthCacheScope, getAuthSessionRevision } from '@/lib/auth-storage'
import { queryKeys } from '@/lib/query-keys'
import { useParsedFiles, type ParsedFileData } from '@/store/use-parsed-files-store'

import type { ParsedFile } from './parsing-types'

type UseParsingQueueActionsOptions = {
  cancelParse: (fileId: string) => void
  filesRef: RefObject<ParsedFile[]>
  moveFolder: (id: string, parentId: string) => boolean
  removeParsedFile: (id: string) => void
  setActiveFileId: Dispatch<SetStateAction<string | null>>
  setActiveLibraryFileId: Dispatch<SetStateAction<string | null>>
  setFiles: Dispatch<SetStateAction<ParsedFile[]>>
  setSelectedGovernanceFileIds: Dispatch<SetStateAction<Set<string>>>
  updateParsedFile: (id: string, updates: Partial<Omit<ParsedFileData, 'id'>>) => Promise<void>
}

export function useParsingQueueActions({
  cancelParse,
  filesRef,
  moveFolder,
  removeParsedFile,
  setActiveFileId,
  setActiveLibraryFileId,
  setFiles,
  setSelectedGovernanceFileIds,
  updateParsedFile,
}: Readonly<UseParsingQueueActionsOptions>) {
  const t = useTranslations('ParsingWorkbench')
  const queryClient = useQueryClient()
  const mountedRef = useRef(false)
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  const removeFile = useCallback(
    async (fileId: string) => {
      const scope = getAuthCacheScope()
      const revision = getAuthSessionRevision()
      const isCurrent = () =>
        mountedRef.current && scope === getAuthCacheScope() && revision === getAuthSessionRevision()
      const queue = filesRef.current.find((file) => file.id === fileId || file.libraryId === fileId)
      if (queue?.status === 'parsing' && queue.libraryId === undefined) {
        throw new Error('源文件正在上传，完成后可以删除')
      }
      const libraryState = useParsedFiles.getState()
      const libraryFiles = libraryState.files
      const libraryId = queue?.libraryId ?? libraryFiles.find((file) => file.id === fileId)?.id
      const libraryEntry = libraryFiles.find((file) => file.id === libraryId)

      if (libraryId !== undefined) {
        if (libraryState.loadError !== undefined) throw libraryState.loadError
        const source = libraryEntry === undefined ? queue?.librarySource : libraryEntry.source
        try {
          if (source === 'knowledge_base') await documentApi.delete(libraryId)
          else if (source === 'parsing_workspace') await parsingApi.delete(libraryId)
          else if (libraryEntry === undefined) throw new Error('文档来源记录不存在，请刷新列表后重试')
        } catch (error) {
          if (isCurrent()) throw error
          return
        }

        if (!isCurrent()) return
        removeParsedFile(libraryId)
        queryClient.removeQueries({ queryKey: ['parsing', 'library-content', libraryId] })
        queryClient.removeQueries({ queryKey: queryKeys.parsing.librarySource(libraryId) })
      }

      const removedFiles = filesRef.current.filter(
        (file) => file.id === fileId || (libraryId !== undefined && file.libraryId === libraryId),
      )
      const removedIds = new Set(removedFiles.map((file) => file.id))
      for (const id of removedIds) cancelParse(id)
      setFiles((previous) => previous.filter((file) => !removedIds.has(file.id)))
      setActiveFileId((current) => (current !== null && removedIds.has(current) ? null : current))
      setActiveLibraryFileId((current) => (current === libraryId ? null : current))
      setSelectedGovernanceFileIds(
        (current) => new Set([...current].filter((id) => !removedIds.has(id) && id !== libraryId)),
      )
    },
    [
      cancelParse,
      filesRef,
      removeParsedFile,
      queryClient,
      setActiveFileId,
      setActiveLibraryFileId,
      setFiles,
      setSelectedGovernanceFileIds,
    ],
  )

  const moveFileToFolder = useCallback(
    async (fileId: string, folderId: string) => {
      const scope = getAuthCacheScope()
      const revision = getAuthSessionRevision()
      const isCurrent = () =>
        mountedRef.current && scope === getAuthCacheScope() && revision === getAuthSessionRevision()
      const queue = filesRef.current.find((file) => file.id === fileId || file.libraryId === fileId)
      const libraryId = queue?.libraryId ?? useParsedFiles.getState().files.find((file) => file.id === fileId)?.id
      try {
        if (libraryId !== undefined) await updateParsedFile(libraryId, { folderId })
        if (!isCurrent()) return
        setFiles((previous) =>
          previous.map((file) =>
            file.id === fileId || (libraryId !== undefined && file.libraryId === libraryId)
              ? { ...file, folderId }
              : file,
          ),
        )
      } catch (error) {
        if (isCurrent()) toast.error(formatApiError(error, '移动文件失败'))
      }
    },
    [filesRef, setFiles, updateParsedFile],
  )

  const handleFileDragStart = useCallback((event: DragEvent<HTMLElement>, fileId: string) => {
    event.dataTransfer.setData('text/plain', fileId)
    event.dataTransfer.effectAllowed = 'move'
  }, [])

  const handleFolderDrop = useCallback(
    async (event: DragEvent<HTMLElement>, folderId: string) => {
      event.preventDefault()
      try {
        const draggedFolderId = event.dataTransfer.getData('application/x-mimirq-folder')
        if (draggedFolderId) {
          const moved = moveFolder(draggedFolderId, folderId)
          if (moved) toast.success(t('toasts.folderMoved'))
          else toast.error(t('toasts.folderMoveInvalid'))
          return
        }
        const fileId = event.dataTransfer.getData('text/plain')
        if (fileId) await moveFileToFolder(fileId, folderId)
      } catch (error) {
        toast.error(formatApiError(error, '移动文件夹失败'))
      }
    },
    [moveFileToFolder, moveFolder, t],
  )

  const handleDeleteFolder = useCallback(
    (folderIds: string[], fileIds: string[]) => {
      const removedIds = new Set(
        filesRef.current.filter((file) => folderIds.includes(file.folderId)).map((file) => file.id),
      )
      for (const id of removedIds) cancelParse(id)
      setFiles((previous) => previous.filter((file) => !removedIds.has(file.id)))
      setActiveFileId((current) => (current !== null && removedIds.has(current) ? null : current))
      setActiveLibraryFileId((current) =>
        useParsedFiles.getState().files.some((file) => file.id === current) ? current : null,
      )
      const removedSelectionIds = new Set([...removedIds, ...fileIds])
      setSelectedGovernanceFileIds((current) => new Set([...current].filter((id) => !removedSelectionIds.has(id))))
    },
    [cancelParse, filesRef, setActiveFileId, setActiveLibraryFileId, setFiles, setSelectedGovernanceFileIds],
  )

  return {
    handleDeleteFolder,
    handleFileDragStart,
    handleFolderDrop,
    moveFileToFolder,
    removeFile,
  }
}
