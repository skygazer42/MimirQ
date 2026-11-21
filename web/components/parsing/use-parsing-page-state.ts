'use client'

import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react'

import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { readClientStorage, writeClientStorage } from '@/lib/client-storage'
import type { ParsingEditSession } from '@/lib/parsing-edit-focus'
import { getParserLabel } from '@/lib/parser-options'
import { resolveParserBackendForFilename } from '@/lib/parser-compat'

import type { ParsedFile } from './parsing-types'

type UseParsingPageStateOptions = {
  files: ParsedFile[]
  setFiles: Dispatch<SetStateAction<ParsedFile[]>>
}

function useParsingBooleanPreference(storageKey: string) {
  const [enabled, setEnabled] = useState(false)
  useEffect(() => {
    setEnabled(readClientStorage(storageKey) === 'true')
  }, [storageKey])
  const updatePreference = useCallback(
    (nextEnabled: boolean) => {
      setEnabled(nextEnabled)
      writeClientStorage(storageKey, nextEnabled ? 'true' : 'false')
    },
    [storageKey],
  )
  return [enabled, updatePreference] as const
}

export function useParsingPageState({ files, setFiles }: Readonly<UseParsingPageStateOptions>) {
  const [activeFileId, setActiveFileId] = useState<string | null>(null)
  const [queueOpen, setQueueOpen] = useState(false)
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const folderInputRef = useRef<HTMLInputElement>(null)
  const uploadTargetFolderIdRef = useRef<string | null>(null)
  const filesRef = useRef(files)
  const parseControllersRef = useRef<Map<string, AbortController>>(new Map())
  const parseProgressIntervalsRef = useRef<Map<string, ReturnType<typeof setInterval>>>(new Map())
  const rebindInputRef = useRef<HTMLInputElement>(null)
  const rebindTargetRef = useRef<{ libraryId: string; autoParse: boolean } | null>(null)
  const [isQueueRehydrating, setIsQueueRehydrating] = useState(false)
  const [autoParseFileId, setAutoParseFileId] = useState<string | null>(null)
  const [activeLibraryFileId, setActiveLibraryFileId] = useState<string | null>(null)
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(null)
  const [previewMode, setPreviewMode] = useState<'raw' | 'rendered'>('rendered')
  const [pdfPreviewResetToken, setPdfPreviewResetToken] = useState(0)
  const [isEditing, setIsEditing] = useState(false)
  const [editedContent, setEditedContent] = useState('')
  const [editSession, setEditSession] = useState<ParsingEditSession | null>(null)
  const [rightPanelMode, setRightPanelMode] = useState<'blocks' | 'markdown'>('markdown')
  const [activeBlockId, setActiveBlockId] = useState<string | null>(null)
  const [hoveredBlockId, setHoveredBlockId] = useState<string | null>(null)
  const { parserBackend, setParserBackend } = useParserBackendPreference()
  const [imageCaptionEnabled, setImageCaptionEnabled] = useParsingBooleanPreference(
    'mimirq_parsing_image_caption_enabled',
  )
  const [imageOcrEnabled, setImageOcrEnabled] = useParsingBooleanPreference('mimirq_parsing_image_ocr_enabled')
  const [vlmCorrectionEnabled, setVlmCorrectionEnabled] = useParsingBooleanPreference(
    'mimirq_parsing_vlm_correction_enabled',
  )

  const cancelParse = useCallback((fileId: string) => {
    const controller = parseControllersRef.current.get(fileId)
    if (controller) {
      controller.abort()
      parseControllersRef.current.delete(fileId)
    }

    const interval = parseProgressIntervalsRef.current.get(fileId)
    if (interval !== undefined) {
      clearInterval(interval)
      parseProgressIntervalsRef.current.delete(fileId)
    }
  }, [])

  useEffect(() => {
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

  const setQueueFileParserBackend = useCallback(
    (params: { fileId: string; filename: string; backend: string }) => {
      const resolved = resolveParserBackendForFilename(params.filename, params.backend)
      const nextBackend = resolved.backend
      const nextLabel = getParserLabel(nextBackend)

      setFiles((prev) =>
        prev.map((file) =>
          file.id === params.fileId ? { ...file, parserBackend: nextBackend, parserLabel: nextLabel } : file,
        ),
      )
    },
    [setFiles],
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
    autoParseFileId,
    cancelParse,
    editSession,
    editedContent,
    fileInputRef,
    filesRef,
    folderInputRef,
    hoveredBlockId,
    imageCaptionEnabled,
    imageOcrEnabled,
    inspectorOpen,
    isEditing,
    isQueueRehydrating,
    parseControllersRef,
    parseProgressIntervalsRef,
    parserBackend,
    pdfPreviewResetToken,
    previewMode,
    queueOpen,
    rebindInputRef,
    rebindTargetRef,
    rightPanelMode,
    selectedDatasetId,
    vlmCorrectionEnabled,
    setActiveBlockId,
    setActiveFileId,
    setActiveLibraryFileId,
    setAutoParseFileId,
    setEditSession,
    setEditedContent,
    setHoveredBlockId,
    setImageCaptionEnabled,
    setImageOcrEnabled,
    setInspectorOpen,
    setIsEditing,
    setIsQueueRehydrating,
    setParserBackend,
    setPdfPreviewResetToken,
    setPreviewMode,
    setQueueFileParserBackend,
    setQueueOpen,
    setRightPanelMode,
    setSelectedDatasetId,
    setVlmCorrectionEnabled,
    consumeUploadTargetFolderId,
    uploadTargetFolderIdRef,
  }
}
