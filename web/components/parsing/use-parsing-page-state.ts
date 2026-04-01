'use client'

import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react'

import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { getParserLabel } from '@/lib/parser-options'
import { resolveParserBackendForFilename } from '@/lib/parser-compat'

import type { ParsedFile } from './parsing-types'

export type ParsingLibrarySourceStatus = 'unknown' | 'available' | 'missing'

type UseParsingPageStateOptions = {
  files: ParsedFile[]
  setFiles: Dispatch<SetStateAction<ParsedFile[]>>
}

export function useParsingPageState({ files, setFiles }: Readonly<UseParsingPageStateOptions>) {
  const [activeFileId, setActiveFileId] = useState<string | null>(null)
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false)
  const [queueOpen, setQueueOpen] = useState(false)
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const [dragOverFolderId, setDragOverFolderId] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const folderInputRef = useRef<HTMLInputElement>(null)
  const uploadTargetFolderIdRef = useRef<string | null>(null)
  const fileIdSetRef = useRef<Set<string>>(new Set())
  const filesRef = useRef<ParsedFile[]>([])
  const rehydratedFolderIdsRef = useRef<Set<string>>(new Set())
  const didSyncLibraryFromServerRef = useRef(false)
  const parseControllersRef = useRef<Map<string, AbortController>>(new Map())
  const parseProgressIntervalsRef = useRef<Map<string, ReturnType<typeof setInterval>>>(new Map())
  const rebindInputRef = useRef<HTMLInputElement>(null)
  const rebindTargetRef = useRef<{ libraryId: string; autoParse: boolean } | null>(null)
  const [isQueueRehydrating, setIsQueueRehydrating] = useState(false)
  const [autoParseFileId, setAutoParseFileId] = useState<string | null>(null)
  const [activeLibraryFileId, setActiveLibraryFileId] = useState<string | null>(null)
  const [activeLibrarySourceStatus, setActiveLibrarySourceStatus] = useState<ParsingLibrarySourceStatus>('unknown')
  const [previewMode, setPreviewMode] = useState<'raw' | 'rendered'>('rendered')
  const [pdfPreviewResetToken, setPdfPreviewResetToken] = useState(0)
  const [isEditing, setIsEditing] = useState(false)
  const [editedContent, setEditedContent] = useState('')
  const [rightPanelMode, setRightPanelMode] = useState<'blocks' | 'markdown'>('blocks')
  const [activeBlockId, setActiveBlockId] = useState<string | null>(null)
  const [hoveredBlockId, setHoveredBlockId] = useState<string | null>(null)
  const { parserBackend, setParserBackend } = useParserBackendPreference()
  const [imageCaptionEnabled, setImageCaptionEnabled] = useState(false)

  const cancelParse = useCallback((fileId: string) => {
    const controller = parseControllersRef.current.get(fileId)
    if (controller) {
      controller.abort()
      parseControllersRef.current.delete(fileId)
    }

    const interval = parseProgressIntervalsRef.current.get(fileId)
    if (interval) {
      clearInterval(interval)
      parseProgressIntervalsRef.current.delete(fileId)
    }
  }, [])

  useEffect(() => {
    fileIdSetRef.current = new Set(files.map((file) => file.id))
    filesRef.current = files
  }, [files])

  useEffect(() => {
    const controllers = parseControllersRef.current
    const intervals = parseProgressIntervalsRef.current

    return () => {
      for (const controller of controllers.values()) {
        controller.abort()
      }
      controllers.clear()

      for (const interval of intervals.values()) {
        clearInterval(interval)
      }
      intervals.clear()
    }
  }, [])

  useEffect(() => {
    if (globalThis.window === undefined) return
    const stored = globalThis.window.localStorage.getItem('mimirq_parsing_image_caption_enabled')
    if (stored === 'true') setImageCaptionEnabled(true)
  }, [])

  useEffect(() => {
    if (globalThis.window === undefined) return
    globalThis.window.localStorage.setItem(
      'mimirq_parsing_image_caption_enabled',
      imageCaptionEnabled ? 'true' : 'false'
    )
  }, [imageCaptionEnabled])

  const setQueueFileParserBackend = useCallback(
    (params: { fileId: string; filename: string; backend: string }) => {
      const resolved = resolveParserBackendForFilename(params.filename, params.backend)
      const nextBackend = resolved.backend
      const nextLabel = getParserLabel(nextBackend)

      setFiles((prev) =>
        prev.map((file) =>
          file.id === params.fileId ? { ...file, parserBackend: nextBackend, parserLabel: nextLabel } : file
        )
      )
      setParserBackend(params.backend)
    },
    [setFiles, setParserBackend]
  )

  const consumeUploadTargetFolderId = useCallback(() => {
    const targetFolderId = uploadTargetFolderIdRef.current
    uploadTargetFolderIdRef.current = null
    return targetFolderId
  }, [])

  return {
    activeBlockId,
    activeFileId,
    activeLibraryFileId,
    activeLibrarySourceStatus,
    autoParseFileId,
    cancelParse,
    copied,
    didSyncLibraryFromServerRef,
    dragOverFolderId,
    editedContent,
    fileIdSetRef,
    fileInputRef,
    filesRef,
    folderInputRef,
    hoveredBlockId,
    imageCaptionEnabled,
    inspectorOpen,
    isEditing,
    isQueueRehydrating,
    isSidebarCollapsed,
    parseControllersRef,
    parseProgressIntervalsRef,
    parserBackend,
    pdfPreviewResetToken,
    previewMode,
    queueOpen,
    rebindInputRef,
    rebindTargetRef,
    rehydratedFolderIdsRef,
    rightPanelMode,
    setActiveBlockId,
    setActiveFileId,
    setActiveLibraryFileId,
    setActiveLibrarySourceStatus,
    setAutoParseFileId,
    setCopied,
    setDragOverFolderId,
    setEditedContent,
    setHoveredBlockId,
    setImageCaptionEnabled,
    setInspectorOpen,
    setIsEditing,
    setIsQueueRehydrating,
    setIsSidebarCollapsed,
    setParserBackend,
    setPdfPreviewResetToken,
    setPreviewMode,
    setQueueFileParserBackend,
    setQueueOpen,
    setRightPanelMode,
    consumeUploadTargetFolderId,
    uploadTargetFolderIdRef,
  }
}

export type ParsingPageState = ReturnType<typeof useParsingPageState>
