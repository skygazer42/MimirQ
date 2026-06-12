'use client'

import { useQueryClient } from '@tanstack/react-query'
import { useCallback, type Dispatch, type DragEvent, type SetStateAction } from 'react'
import { useTranslations } from 'next-intl'

import { toast } from 'sonner'

import { documentApi, parsingApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { ROOT_FOLDER_ID, type ParsedFileData } from '@/store/use-parsed-files-store'

import type { ParsedFile } from './parsing-types'

type UseParsingQueueActionsOptions = {
  activeFileId: string | null
  activeLibraryFileId: string | null
  cancelParse: (fileId: string) => void
  files: ParsedFile[]
  libraryFiles: ParsedFileData[]
  moveFolder: (id: string, parentId: string) => boolean
  removeLibraryCaches: (fileId: string) => void
  removeParsedFile: (id: string) => void
  setActiveFileId: Dispatch<SetStateAction<string | null>>
  setActiveLibraryFileId: Dispatch<SetStateAction<string | null>>
  setDragOverFolderId: Dispatch<SetStateAction<string | null>>
  setFiles: Dispatch<SetStateAction<ParsedFile[]>>
  updateParsedFile: (id: string, updates: Partial<Omit<ParsedFileData, 'id'>>) => void
}

export function useParsingQueueActions({
  activeFileId,
  activeLibraryFileId,
  cancelParse,
  files,
  libraryFiles,
  moveFolder,
  removeLibraryCaches,
  removeParsedFile,
  setActiveFileId,
  setActiveLibraryFileId,
  setDragOverFolderId,
  setFiles,
  updateParsedFile,
}: Readonly<UseParsingQueueActionsOptions>) {
  const t = useTranslations('ParsingWorkbench')
  const queryClient = useQueryClient()

  const removeFile = useCallback(
    (fileId: string) => {
      const queue = files.find((file) => file.id === fileId) || null
      const libraryId = queue?.libraryId || (libraryFiles.some((file) => file.id === fileId) ? fileId : null)
      const libraryEntry = libraryId ? libraryFiles.find((file) => file.id === libraryId) || null : null

      if (queue) {
        cancelParse(queue.id)
        setFiles((prev) => prev.filter((file) => file.id !== queue.id))
        if (activeFileId === queue.id) setActiveFileId(null)
      }

      if (libraryId) {
        queryClient.setQueriesData<ParsedFileData[] | null>({ queryKey: ['parsing', 'library-documents'] }, (current) => {
          if (!Array.isArray(current)) return current
          return current.filter((file) => file.id !== libraryId)
        })
        queryClient.removeQueries({ queryKey: ['parsing', 'library-content', libraryId] })

        void (async () => {
          try {
            if (libraryEntry?.source === 'knowledge_base') await documentApi.delete(libraryId)
            else await parsingApi.delete(libraryId)
          } catch (err: unknown) {
            toast.error(formatApiError(err, t('toasts.deleteFailed')))
          }
        })()

        removeParsedFile(libraryId)
        removeLibraryCaches(libraryId)
        if (activeLibraryFileId === libraryId) setActiveLibraryFileId(null)
      }
    },
    [
      activeFileId,
      activeLibraryFileId,
      cancelParse,
      files,
      libraryFiles,
      removeLibraryCaches,
      removeParsedFile,
      queryClient,
      setActiveFileId,
      setActiveLibraryFileId,
      setFiles,
      t,
    ]
  )

  const moveFileToFolder = useCallback(
    (fileId: string, folderId: string) => {
      const targetId = folderId || ROOT_FOLDER_ID
      setFiles((prev) => prev.map((file) => (file.id === fileId ? { ...file, folderId: targetId } : file)))

      const queueMatch = files.find((file) => file.id === fileId) || null
      const libraryId = queueMatch?.libraryId || (libraryFiles.some((file) => file.id === fileId) ? fileId : null)
      if (libraryId) updateParsedFile(libraryId, { folderId: targetId })
    },
    [files, libraryFiles, setFiles, updateParsedFile]
  )

  const handleFileDragStart = useCallback((event: DragEvent<HTMLElement>, fileId: string) => {
    event.dataTransfer.setData('text/plain', fileId)
    event.dataTransfer.effectAllowed = 'move'
  }, [])

  const handleFolderDragOver = useCallback(
    (event: DragEvent<HTMLElement>, folderId: string) => {
      event.preventDefault()
      setDragOverFolderId(folderId)
    },
    [setDragOverFolderId]
  )

  const handleFolderDragLeave = useCallback(() => {
    setDragOverFolderId(null)
  }, [setDragOverFolderId])

  const handleFolderDrop = useCallback(
    (event: DragEvent<HTMLElement>, folderId: string) => {
      event.preventDefault()
      const targetId = folderId || ROOT_FOLDER_ID

      const draggedFolderId = event.dataTransfer.getData('application/x-mimirq-folder')
      if (draggedFolderId) {
        const ok = moveFolder(draggedFolderId, targetId)
        if (ok) toast.success(t('toasts.folderMoved'))
        else toast.error(t('toasts.folderMoveInvalid'))
        setDragOverFolderId(null)
        return
      }

      const fileId = event.dataTransfer.getData('text/plain')
      if (fileId) moveFileToFolder(fileId, targetId)
      setDragOverFolderId(null)
    },
    [moveFileToFolder, moveFolder, setDragOverFolderId, t]
  )

  const handleDeleteFolder = useCallback(
    (folderIds: string[]) => {
      setFiles((prev) => prev.filter((file) => !file.folderId || !folderIds.includes(file.folderId)))
    },
    [setFiles]
  )

  return {
    handleDeleteFolder,
    handleFileDragStart,
    handleFolderDragLeave,
    handleFolderDragOver,
    handleFolderDrop,
    moveFileToFolder,
    removeFile,
  }
}
