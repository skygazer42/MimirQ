'use client'

import { useCallback, useEffect, useRef, useState, type Dispatch, type RefObject, type SetStateAction } from 'react'
import { useTranslations } from 'next-intl'

import { toast } from 'sonner'

import { useRouter } from '@/i18n/navigation'
import { parsingApi } from '@/lib/api/parsing'
import { formatApiError } from '@/lib/api-errors'
import { getAuthCacheScope, getAuthSessionRevision } from '@/lib/auth-storage'
import { downloadBlob } from '@/lib/download'
import {
  applyBlockEditToMarkdown,
  buildParsingBlockEditTarget,
  type ParsingEditSession,
} from '@/lib/parsing-edit-focus'
import { buildParsingLayoutEntries } from '@/lib/parsing-layout'
import type { ParsingBlock } from '@/lib/parsing-positions'
import { useParsedFiles, type ParsedFileData } from '@/store/use-parsed-files-store'

import type { ParsedFile, ParseRun } from './parsing-types'
import { buildParsingStatistics, getActiveParsingRun } from './parsing-page-utils'
import { loadParsingLibraryContent, type ParsingLibraryContent } from './parsing-library-content'
import { getParsingGovernanceTargets, type ParsingGovernanceTarget } from './parsing-governance'

function applyEditedMarkdown(
  prev: ParsedFile[],
  fileId: string,
  targetRunId: string | undefined,
  content: ParsingLibraryContent,
): ParsedFile[] {
  const stats = buildParsingStatistics(content.markdownContent, 0, content.stats)
  return prev.map((file) => {
    if (file.id !== fileId) return file

    const runs =
      targetRunId !== undefined && file.runs !== undefined
        ? file.runs.map((run) =>
            run.id === targetRunId
              ? {
                  ...run,
                  cleanedMarkdown: content.markdownContent,
                  rawMarkdown: content.originalMarkdownContent,
                  blocks: [],
                  parserBackend: content.parserBackend ?? run.parserBackend,
                  parserLabel: content.parser ?? run.parserLabel,
                  stats,
                  durationSec: content.durationSec,
                  elements: content.elements,
                  pdfQuality: content.pdfQuality,
                  qualityGate: content.qualityGate,
                  contentEdited: true,
                }
              : run,
          )
        : file.runs

    const savedRunId = file.librarySource === 'parsing_workspace' ? targetRunId : undefined
    if (getActiveParsingRun(file)?.id !== targetRunId) return { ...file, runs, savedRunId }

    return {
      ...file,
      governanceStatus: 'ready',
      markdownContent: content.markdownContent,
      runs,
      savedRunId,
      parserBackend: content.parserBackend ?? file.parserBackend,
      parserLabel: content.parser ?? file.parserLabel,
      stats,
      duration: content.durationSec,
      elements: content.elements,
      pdfQuality: content.pdfQuality,
      qualityGate: content.qualityGate,
      contentEdited: true,
    }
  })
}

function getQueueContent(file: ParsedFile, libraryFile: ParsedFileData): ParsingLibraryContent {
  const run = getActiveParsingRun(file)
  if (file.librarySource !== 'knowledge_base' && file.activeRunId !== undefined && run === undefined)
    throw new Error('所选解析版本不可用，请重新选择后重试')
  if (run !== undefined) {
    return {
      contentLoaded: true,
      markdownContent: run.cleanedMarkdown,
      originalMarkdownContent: run.rawMarkdown,
      parser: run.parserLabel,
      parserBackend: run.parserBackend,
      durationSec: run.durationSec,
      elements: run.elements,
      contentEdited: run.contentEdited,
    }
  }
  const markdownContent = file.markdownContent
  if (markdownContent === null) throw new Error('解析正文尚未加载，请先打开文档后重试')
  return {
    contentLoaded: true,
    markdownContent,
    originalMarkdownContent: libraryFile.originalMarkdownContent ?? markdownContent,
    parser: file.parserLabel,
    parserBackend: file.parserBackend,
    durationSec: file.duration,
    elements: file.elements,
    contentEdited: file.contentEdited,
  }
}

type GovernanceRequest = { scope: string; revision: number }

type UseParsingEditorActionsOptions = {
  activeBlockId: string | null
  activeBlocksWithPositions: ParsingBlock[]
  activeFile: ParsedFile | null
  activeMarkdown: string
  activeRun: ParseRun | null
  currentFolderId: string
  editSession: ParsingEditSession | null
  editedContent: string
  filesRef: RefObject<ParsedFile[]>
  queueFiles: ParsedFile[]
  libraryFiles: ParsedFileData[]
  selectedDatasetId: string | null
  selectedGovernanceFileIds: ReadonlySet<string>
  setActiveBlockId: Dispatch<SetStateAction<string | null>>
  setEditSession: Dispatch<SetStateAction<ParsingEditSession | null>>
  setEditedContent: Dispatch<SetStateAction<string>>
  setFiles: Dispatch<SetStateAction<ParsedFile[]>>
  setHoveredBlockId: Dispatch<SetStateAction<string | null>>
  setIsEditing: Dispatch<SetStateAction<boolean>>
  setRightPanelMode: Dispatch<SetStateAction<'blocks' | 'markdown'>>
  setSelectedGovernanceFileIds: Dispatch<SetStateAction<Set<string>>>
  updateParsedFile: (
    id: string,
    updates: Partial<Omit<ParsedFileData, 'id'>>,
    options?: { requirePersistence?: boolean },
  ) => Promise<void>
}

export function useParsingEditorActions({
  activeBlockId,
  activeBlocksWithPositions,
  activeFile,
  activeMarkdown,
  activeRun,
  currentFolderId,
  editSession,
  editedContent,
  filesRef,
  queueFiles,
  libraryFiles,
  selectedDatasetId,
  selectedGovernanceFileIds,
  setActiveBlockId,
  setEditSession,
  setEditedContent,
  setFiles,
  setHoveredBlockId,
  setIsEditing,
  setRightPanelMode,
  setSelectedGovernanceFileIds,
  updateParsedFile,
}: Readonly<UseParsingEditorActionsOptions>) {
  const router = useRouter()
  const t = useTranslations('ParsingWorkbench')
  const [copied, setCopied] = useState(false)
  const mountedRef = useRef(false)
  const copyRequestRef = useRef<object | undefined>(undefined)
  const copyTimeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const governanceRequestRef = useRef<GovernanceRequest | null>(null)
  const [governanceRequest, setGovernanceRequest] = useState<GovernanceRequest | null>(null)
  const handoffContextRef = useRef({ currentFolderId, selectedDatasetId, selectedGovernanceFileIds })
  const editRef = useRef({ fileId: activeFile?.id, runId: activeRun?.id, editSession, editedContent })
  useEffect(() => {
    editRef.current = { fileId: activeFile?.id, runId: activeRun?.id, editSession, editedContent }
  }, [activeFile?.id, activeRun?.id, editSession, editedContent])
  useEffect(() => {
    handoffContextRef.current = { currentFolderId, selectedDatasetId, selectedGovernanceFileIds }
  }, [currentFolderId, selectedDatasetId, selectedGovernanceFileIds])
  useEffect(() => {
    setCopied(false)
    return () => {
      copyRequestRef.current = undefined
      clearTimeout(copyTimeoutRef.current)
    }
  }, [activeFile?.id, activeRun?.id, activeMarkdown, setCopied])
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  const copyMarkdown = useCallback(async () => {
    if (!activeFile || activeFile.status !== 'parsed') return
    const request = {}
    copyRequestRef.current = request
    const scope = getAuthCacheScope()
    const revision = getAuthSessionRevision()
    const isCurrent = () =>
      mountedRef.current &&
      copyRequestRef.current === request &&
      scope === getAuthCacheScope() &&
      revision === getAuthSessionRevision()
    try {
      await navigator.clipboard.writeText(activeMarkdown)
      if (!isCurrent()) return
      clearTimeout(copyTimeoutRef.current)
      setCopied(true)
      copyTimeoutRef.current = setTimeout(() => setCopied(false), 2000)
    } catch (error) {
      if (isCurrent()) toast.error(formatApiError(error, t('libraryPreview.copyFailed')))
    }
  }, [activeFile, activeMarkdown, setCopied, t])

  const downloadMarkdown = useCallback(() => {
    if (!activeFile || activeFile.status !== 'parsed') return
    const blob = new Blob([activeMarkdown], { type: 'text/markdown' })
    downloadBlob(activeFile.file.name.replace(/\.[^/.]+$/, '') + '.md', blob)
  }, [activeFile, activeMarkdown])

  const handleStartEdit = useCallback(() => {
    if (!activeFile || activeFile.status !== 'parsed' || activeFile.librarySource === 'knowledge_base') return
    const owner = {
      fileId: activeFile.id,
      libraryId: activeFile.libraryId,
      runId: activeRun?.id ?? activeFile.activeRunId,
    }
    const blockEditTarget = buildParsingBlockEditTarget(
      activeMarkdown,
      buildParsingLayoutEntries(activeBlocksWithPositions),
      activeBlockId,
    )

    if (blockEditTarget) {
      setEditSession({
        ...owner,
        mode: 'block',
        blockId: blockEditTarget.blockId,
        range: blockEditTarget.range,
        sourceMarkdown: activeMarkdown,
      })
      setEditedContent(blockEditTarget.content)
    } else {
      setEditSession({ ...owner, mode: 'document' })
      setEditedContent(activeMarkdown)
    }

    setIsEditing(true)
  }, [
    activeBlockId,
    activeBlocksWithPositions,
    activeFile,
    activeMarkdown,
    activeRun,
    setEditSession,
    setEditedContent,
    setIsEditing,
  ])

  const handleCancelEdit = useCallback(() => {
    setEditSession(null)
    setIsEditing(false)
    setEditedContent('')
  }, [setEditSession, setEditedContent, setIsEditing])

  const handleSaveEdit = useCallback(async () => {
    if (!activeFile || activeFile.librarySource === 'knowledge_base' || editSession === null) return
    const targetRunId = activeRun?.id ?? activeFile.activeRunId
    if (
      editSession.fileId !== activeFile.id ||
      editSession.libraryId !== activeFile.libraryId ||
      editSession.runId !== targetRunId
    ) {
      toast.error('文件或解析版本已变化，当前编辑草稿已保留。')
      return
    }
    const scope = getAuthCacheScope()
    const revision = getAuthSessionRevision()
    const edit = editRef.current
    const isCurrent = () =>
      mountedRef.current &&
      scope === getAuthCacheScope() &&
      revision === getAuthSessionRevision() &&
      filesRef.current.some((file) => file.id === activeFile.id && file.libraryId === activeFile.libraryId)
    const nextMarkdown =
      editSession.mode === 'block'
        ? applyBlockEditToMarkdown(editSession.sourceMarkdown, editSession.range, editedContent)
        : editedContent

    try {
      const libraryId = activeFile.libraryId
      if (libraryId === undefined) throw new Error('文档尚未加入文档库，请先重新解析')
      const libraryFile = useParsedFiles.getState().files.find((file) => file.id === libraryId)
      if (libraryFile === undefined) throw new Error('文档库条目已移除，请重新选择')
      let content: ParsingLibraryContent = {
        ...getQueueContent(activeFile, libraryFile),
        markdownContent: nextMarkdown,
        elements: undefined,
        pdfQuality: undefined,
        qualityGate: undefined,
        contentEdited: true,
      }
      if (activeFile.librarySource === 'parsing_workspace') {
        const saved = await parsingApi.updateContent(libraryId, {
          markdown_content: nextMarkdown,
          original_markdown_content: content.originalMarkdownContent,
          parser_backend: content.parserBackend,
          parse_duration_sec: content.durationSec === undefined ? null : content.durationSec,
        })
        if (!isCurrent()) return
        content = {
          ...content,
          markdownContent: saved.markdown_content,
          originalMarkdownContent: saved.original_markdown_content,
        }
      }
      const updates = {
        markdownContent: content.markdownContent,
        originalMarkdownContent: content.originalMarkdownContent,
        status: 'parsed' as const,
        error: undefined,
        governanceStatus: 'ready' as const,
        parser: content.parser,
        parserBackend: content.parserBackend,
        durationSec: content.durationSec,
        elements: content.elements,
        pdfQuality: content.pdfQuality,
        qualityGate: content.qualityGate,
        contentEdited: true,
      }
      if (activeFile.librarySource === undefined) {
        await updateParsedFile(libraryId, updates, { requirePersistence: true })
      } else {
        try {
          await updateParsedFile(libraryId, updates)
        } catch (error) {
          if (isCurrent()) toast.error(`正文已保存到服务器，但本地状态更新失败：${formatApiError(error, '请重试更新')}`)
          return
        }
      }
      if (!isCurrent()) return
      setFiles((prev) => applyEditedMarkdown(prev, activeFile.id, targetRunId, content))
      if (editRef.current !== edit) return
      setRightPanelMode('markdown')
      setActiveBlockId(null)
      setEditSession(null)
      setHoveredBlockId(null)
      setIsEditing(false)
      toast.success(t(activeFile.librarySource === undefined ? 'toasts.localSaveSuccess' : 'toasts.saveSuccess'))
    } catch (err: unknown) {
      if (isCurrent()) toast.error(formatApiError(err, t('toasts.saveFailed')))
    }
  }, [
    activeFile,
    activeRun,
    editSession,
    editedContent,
    filesRef,
    setActiveBlockId,
    setEditSession,
    setFiles,
    setHoveredBlockId,
    setIsEditing,
    setRightPanelMode,
    t,
    updateParsedFile,
  ])

  const submitGovernanceFiles = useCallback(
    async (targets: ParsingGovernanceTarget[]) => {
      if (targets.length === 0) {
        toast.error('没有可移交的待治理文档')
        return
      }
      const request = { scope: getAuthCacheScope(), revision: getAuthSessionRevision() }
      const pending = governanceRequestRef.current
      if (pending !== null && pending.scope === request.scope && pending.revision === request.revision) return
      governanceRequestRef.current = request
      setGovernanceRequest(request)
      const context = handoffContextRef.current
      const edit = editRef.current
      const isCurrent = () =>
        mountedRef.current &&
        governanceRequestRef.current === request &&
        request.scope === getAuthCacheScope() &&
        request.revision === getAuthSessionRevision()
      const completedIds = new Set<string>()
      const failures: string[] = []
      let submittedCount = 0
      try {
        for (const target of targets) {
          if (!isCurrent()) return
          if (handoffContextRef.current !== context || editRef.current !== edit) break
          try {
            if (target.kind === 'queue' && !filesRef.current.some((item) => item.id === target.file.id))
              throw new Error('队列文档已移除，请重新选择')
            const libraryId = target.kind === 'queue' ? target.file.libraryId : target.file.id
            if (libraryId === undefined) throw new Error('文档尚未加入文档库，请先重新解析')
            const libraryFile = useParsedFiles.getState().files.find((item) => item.id === libraryId)
            if (libraryFile === undefined) throw new Error('文档库条目已移除，请重新选择')
            let content: ParsingLibraryContent
            if (target.kind === 'library' || target.file.librarySource === 'knowledge_base') {
              const result = await loadParsingLibraryContent(libraryFile)
              if (!isCurrent()) return
              const currentFile = useParsedFiles.getState().files.find((item) => item.id === libraryId)
              if (
                currentFile === undefined ||
                currentFile.source !== libraryFile.source ||
                (currentFile.status ?? 'parsed') !== 'parsed' ||
                currentFile.markdownContent !== libraryFile.markdownContent ||
                currentFile.originalMarkdownContent !== libraryFile.originalMarkdownContent
              )
                throw new Error('文档已更新，请重新选择后重试')
              if (result.status !== 'parsed' || result.content === undefined)
                throw new Error('文档尚未解析完成，请稍后重试')
              content = result.content
            } else {
              content = getQueueContent(target.file, libraryFile)
            }
            await updateParsedFile(
              libraryId,
              { ...content, governanceStatus: 'submitted', status: 'parsed', error: undefined },
              { requirePersistence: true },
            )
            if (!isCurrent()) return
            const submitted = useParsedFiles.getState().files.find((item) => item.id === libraryId)
            if (
              submitted === undefined ||
              submitted.status !== 'parsed' ||
              submitted.governanceStatus !== 'submitted' ||
              submitted.markdownContent !== content.markdownContent ||
              submitted.originalMarkdownContent !== content.originalMarkdownContent
            )
              throw new Error('文档移交未完成，请重试')
            submittedCount += 1
            if (target.kind === 'queue') {
              const currentQueue = filesRef.current.find((item) => item.id === target.file.id)
              if (
                currentQueue === undefined ||
                currentQueue.libraryId !== libraryId ||
                currentQueue.status !== 'parsed'
              )
                continue
              if (currentQueue.librarySource !== 'knowledge_base') {
                if (
                  currentQueue.activeRunId !== target.file.activeRunId ||
                  getActiveParsingRun(currentQueue)?.id !== getActiveParsingRun(target.file)?.id
                )
                  continue
                const currentContent = getQueueContent(currentQueue, submitted)
                if (
                  currentContent.markdownContent !== content.markdownContent ||
                  currentContent.originalMarkdownContent !== content.originalMarkdownContent
                )
                  continue
              }
              setFiles((previous) =>
                previous.map((item) =>
                  item.id === target.file.id ? { ...item, libraryId, governanceStatus: 'submitted' } : item,
                ),
              )
            }
            completedIds.add(target.selectionId)
          } catch (error) {
            if (!isCurrent()) return
            const filename = target.kind === 'queue' ? target.file.name : target.file.filename
            failures.push(`${filename}：${formatApiError(error, '移交数据治理失败')}`)
          }
        }
        if (!isCurrent()) return
        const canNavigate = handoffContextRef.current === context && editRef.current === edit
        setSelectedGovernanceFileIds((current) => new Set([...current].filter((id) => !completedIds.has(id))))
        if (failures.length > 0) {
          toast.error(`已移交 ${submittedCount} 个，${failures.length} 个失败：${failures.join('；')}`)
          return
        }
        if (canNavigate) {
          toast.success(`已移交 ${submittedCount} 个文档到数据治理`)
          router.push('/data-governance')
        }
      } finally {
        if (governanceRequestRef.current === request) {
          governanceRequestRef.current = null
          if (mountedRef.current) setGovernanceRequest(null)
        }
      }
    },
    [filesRef, router, setFiles, setSelectedGovernanceFileIds, updateParsedFile],
  )

  const handleSubmitToGovernance = useCallback(
    async (libraryFile?: ParsedFileData) => {
      if (libraryFile) {
        if ((libraryFile.status ?? 'parsed') !== 'parsed') return
        await submitGovernanceFiles([{ kind: 'library', file: libraryFile, selectionId: libraryFile.id }])
        return
      }
      if (!activeFile || activeFile.status !== 'parsed') return
      await submitGovernanceFiles([
        { kind: 'queue', file: activeFile, selectionId: activeFile.libraryId ?? activeFile.id },
      ])
    },
    [activeFile, submitGovernanceFiles],
  )

  const handleSubmitSelectedToGovernance = useCallback(async () => {
    const targets = getParsingGovernanceTargets(queueFiles, libraryFiles, selectedDatasetId).filter((target) =>
      selectedGovernanceFileIds.has(target.selectionId),
    )
    await submitGovernanceFiles(targets)
  }, [libraryFiles, queueFiles, selectedDatasetId, selectedGovernanceFileIds, submitGovernanceFiles])

  return {
    copyMarkdown,
    copied,
    downloadMarkdown,
    handleCancelEdit,
    handleSaveEdit,
    handleStartEdit,
    handleSubmitSelectedToGovernance,
    handleSubmitToGovernance,
    isSubmittingGovernance:
      governanceRequest !== null &&
      governanceRequest.scope === getAuthCacheScope() &&
      governanceRequest.revision === getAuthSessionRevision(),
  }
}
