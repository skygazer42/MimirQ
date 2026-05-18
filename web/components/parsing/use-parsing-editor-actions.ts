'use client'

import { useCallback, type Dispatch, type SetStateAction } from 'react'
import { useTranslations } from 'next-intl'

import { toast } from 'sonner'

import { useRouter } from '@/i18n/navigation'
import { parsingApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import {
  applyBlockEditToMarkdown,
  buildParsingBlockEditTarget,
  type ParsingEditSession,
} from '@/lib/parsing-edit-focus'
import { buildParsingLayoutEntries } from '@/lib/parsing-layout'
import { getParserLabel } from '@/lib/parser-options'
import type { ParsingBlock } from '@/lib/parsing-positions'
import { type ParsedFileData } from '@/store/use-parsed-files-store'

import type { ParsedFile, ParseRun } from './parsing-types'

function applyEditedMarkdown(
  prev: ParsedFile[],
  fileId: string,
  targetRunId: string | undefined,
  editedContent: string,
  countMarkdownHeadings: (markdown: string) => number
): ParsedFile[] {
  return prev.map((file) => {
    if (file.id !== fileId) return file

    const runs =
      targetRunId && file.runs
        ? file.runs.map((run) =>
            run.id === targetRunId
              ? {
                  ...run,
                  cleanedMarkdown: editedContent,
                  rawMarkdown: editedContent,
                  blocks: [],
                }
              : run
          )
        : file.runs

    return {
      ...file,
      governanceStatus: 'ready',
      markdownContent: editedContent,
      runs,
      stats: file.stats
        ? {
            ...file.stats,
            charCount: editedContent.length,
            lineCount: editedContent.split('\n').length,
            headingCount: countMarkdownHeadings(editedContent),
            blockCount: 0,
          }
        : undefined,
    }
  })
}

function getParsedMarkdown(file: ParsedFile): string {
  const activeRun = file.runs?.find((run) => run.id === file.activeRunId) ?? file.runs?.[0]
  return activeRun?.cleanedMarkdown || file.markdownContent || ''
}

function buildGovernanceLibraryPayload(
  file: ParsedFile,
  markdown: string,
  governanceStatus: 'ready' | 'submitted'
): Omit<ParsedFileData, 'id' | 'parsedAt'> {
  return {
    filename: file.file.name,
    fileType: file.file.name.split('.').pop()?.toLowerCase() || '',
    fileSize: file.file.size,
    markdownContent: markdown,
    originalMarkdownContent: markdown,
    parser: file.parserLabel,
    folderId: file.folderId,
    status: 'parsed',
    error: undefined,
    governanceStatus,
  }
}

type UseParsingEditorActionsOptions = {
  activeBlockId: string | null
  activeBlocksWithPositions: ParsingBlock[]
  activeFile: ParsedFile | null
  activeMarkdown: string
  activeRun: ParseRun | null
  addParsedFile: (file: Omit<ParsedFileData, 'id' | 'parsedAt'>) => string
  countMarkdownHeadings: (markdown: string) => number
  editSession: ParsingEditSession | null
  editedContent: string
  files: ParsedFile[]
  libraryFiles: ParsedFileData[]
  selectedGovernanceFileIds: ReadonlySet<string>
  setActiveBlockId: Dispatch<SetStateAction<string | null>>
  setCopied: Dispatch<SetStateAction<boolean>>
  setEditSession: Dispatch<SetStateAction<ParsingEditSession | null>>
  setEditedContent: Dispatch<SetStateAction<string>>
  setFiles: Dispatch<SetStateAction<ParsedFile[]>>
  setHoveredBlockId: Dispatch<SetStateAction<string | null>>
  setIsEditing: Dispatch<SetStateAction<boolean>>
  setRightPanelMode: Dispatch<SetStateAction<'blocks' | 'markdown'>>
  setSelectedGovernanceFileIds: Dispatch<SetStateAction<Set<string>>>
  updateParsedFile: (id: string, updates: Partial<Omit<ParsedFileData, 'id'>>) => Promise<void>
}

export function useParsingEditorActions({
  activeBlockId,
  activeBlocksWithPositions,
  activeFile,
  activeMarkdown,
  activeRun,
  addParsedFile,
  countMarkdownHeadings,
  editSession,
  editedContent,
  files,
  libraryFiles,
  selectedGovernanceFileIds,
  setActiveBlockId,
  setCopied,
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

  const copyMarkdown = useCallback(async () => {
    if (!activeMarkdown) return
    await navigator.clipboard.writeText(activeMarkdown)
    setCopied(true)
    globalThis.window.setTimeout(() => setCopied(false), 2000)
  }, [activeMarkdown, setCopied])

  const downloadMarkdown = useCallback(() => {
    if (!activeFile || !activeMarkdown) return
    const blob = new Blob([activeMarkdown], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = activeFile.file.name.replace(/\.[^/.]+$/, '') + '.md'
    anchor.click()
    URL.revokeObjectURL(url)
  }, [activeFile, activeMarkdown])

  const handleStartEdit = useCallback(() => {
    if (!activeMarkdown) return
    const blockEditTarget = buildParsingBlockEditTarget(
      activeMarkdown,
      buildParsingLayoutEntries(activeBlocksWithPositions),
      activeBlockId
    )

    if (blockEditTarget) {
      setEditSession({
        mode: 'block',
        blockId: blockEditTarget.blockId,
        range: blockEditTarget.range,
        sourceMarkdown: activeMarkdown,
      })
      setEditedContent(blockEditTarget.content)
    } else {
      setEditSession({ mode: 'document' })
      setEditedContent(activeMarkdown)
    }

    setIsEditing(true)
  }, [activeBlockId, activeBlocksWithPositions, activeMarkdown, setEditSession, setEditedContent, setIsEditing])

  const handleCancelEdit = useCallback(() => {
    setEditSession(null)
    setIsEditing(false)
    setEditedContent('')
  }, [setEditSession, setEditedContent, setIsEditing])

  const handleSaveEdit = useCallback(async () => {
    if (!activeFile) return
    const targetRunId = activeRun?.id ?? activeFile.activeRunId
    const nextMarkdown =
      editSession?.mode === 'block'
        ? applyBlockEditToMarkdown(editSession.sourceMarkdown, editSession.range, editedContent)
        : editSession
          ? editedContent
          : activeMarkdown

    setFiles((prev) => applyEditedMarkdown(prev, activeFile.id, targetRunId, nextMarkdown, countMarkdownHeadings))
    setRightPanelMode('markdown')
    setActiveBlockId(null)
    setEditSession(null)
    setHoveredBlockId(null)
    setIsEditing(false)

    const libId = (activeFile.libraryId || '').trim()
    if (!libId) return

    try {
      const saved = await parsingApi.updateContent(libId, { markdown_content: nextMarkdown })
      await updateParsedFile(libId, {
        markdownContent: saved.markdown_content || nextMarkdown,
        originalMarkdownContent: saved.original_markdown_content || nextMarkdown,
        status: 'parsed',
        error: undefined,
        parser: getParserLabel(saved.parser_backend || 'auto'),
        governanceStatus: 'ready',
      })
      toast.success(t('toasts.saveSuccess'))
    } catch (err: unknown) {
      toast.error(formatApiError(err, t('toasts.saveFailed')))
    }
  }, [
    activeFile,
    activeMarkdown,
    activeRun,
    countMarkdownHeadings,
    editSession,
    editedContent,
    setActiveBlockId,
    setEditSession,
    setFiles,
    setHoveredBlockId,
    setIsEditing,
    setRightPanelMode,
    t,
    updateParsedFile,
  ])

  const handleSubmitToGovernance = useCallback(async () => {
    if (!activeFile || !activeMarkdown) return

    if (activeFile.libraryId) {
      await updateParsedFile(activeFile.libraryId, {
        markdownContent: activeMarkdown,
        originalMarkdownContent: activeMarkdown,
        parser: activeFile.parserLabel,
        status: 'parsed',
        error: undefined,
        governanceStatus: 'submitted',
      })
    } else {
      const libraryId = addParsedFile(buildGovernanceLibraryPayload(activeFile, activeMarkdown, 'submitted'))
      setFiles((prev) =>
        prev.map((file) =>
          file.id === activeFile.id ? { ...file, governanceStatus: 'submitted', libraryId } : file
        )
      )
    }

    setSelectedGovernanceFileIds((prev) => {
      const next = new Set(prev)
      next.delete(activeFile.id)
      if (activeFile.libraryId) next.delete(activeFile.libraryId)
      return next
    })
    router.push('/data-governance')
  }, [activeFile, activeMarkdown, addParsedFile, router, setFiles, setSelectedGovernanceFileIds, updateParsedFile])

  const handleSubmitSelectedToGovernance = useCallback(async () => {
    const selectedIds = new Set(selectedGovernanceFileIds)
    if (selectedIds.size === 0) return

    const newLibraryIdsByFileId = new Map<string, string>()
    let submittedCount = 0

    try {
      for (const file of files) {
        if (!selectedIds.has(file.id) || file.governanceStatus !== 'ready') continue

        const markdown = getParsedMarkdown(file)
        if (!markdown.trim()) continue

        if (file.libraryId) {
          await updateParsedFile(file.libraryId, {
            ...buildGovernanceLibraryPayload(file, markdown, 'submitted'),
          })
        } else {
          const libraryId = addParsedFile(buildGovernanceLibraryPayload(file, markdown, 'submitted'))
          newLibraryIdsByFileId.set(file.id, libraryId)
        }
        submittedCount += 1
      }

      for (const file of libraryFiles) {
        if (!selectedIds.has(file.id) || file.governanceStatus !== 'ready') continue
        if (!file.markdownContent.trim()) continue

        await updateParsedFile(file.id, {
          markdownContent: file.markdownContent,
          originalMarkdownContent: file.originalMarkdownContent || file.markdownContent,
          parser: file.parser,
          status: 'parsed',
          error: undefined,
          governanceStatus: 'submitted',
        })
        submittedCount += 1
      }

      if (submittedCount === 0) {
        toast.error('没有可提交的待提交文档')
        return
      }

      setFiles((prev) =>
        prev.map((file) =>
          selectedIds.has(file.id)
            ? {
                ...file,
                governanceStatus: 'submitted',
                libraryId: newLibraryIdsByFileId.get(file.id) || file.libraryId,
              }
            : file
        )
      )
      setSelectedGovernanceFileIds(new Set())
      toast.success(`已提交 ${submittedCount} 个文档到数据治理`)
      router.push('/data-governance')
    } catch (err: unknown) {
      toast.error(formatApiError(err, '批量提交失败'))
    }
  }, [
    addParsedFile,
    files,
    libraryFiles,
    router,
    selectedGovernanceFileIds,
    setFiles,
    setSelectedGovernanceFileIds,
    updateParsedFile,
  ])

  return {
    copyMarkdown,
    downloadMarkdown,
    handleCancelEdit,
    handleSaveEdit,
    handleStartEdit,
    handleSubmitSelectedToGovernance,
    handleSubmitToGovernance,
  }
}
