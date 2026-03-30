'use client'

import { useCallback, type Dispatch, type SetStateAction } from 'react'

import { toast } from 'sonner'

import { useRouter } from '@/i18n/navigation'
import { parsingApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { getParserLabel } from '@/lib/parser-options'
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

type UseParsingEditorActionsOptions = {
  activeFile: ParsedFile | null
  activeMarkdown: string
  activeRun: ParseRun | null
  addParsedFile: (file: Omit<ParsedFileData, 'id' | 'parsedAt'>) => string
  countMarkdownHeadings: (markdown: string) => number
  editedContent: string
  setActiveBlockId: Dispatch<SetStateAction<string | null>>
  setCopied: Dispatch<SetStateAction<boolean>>
  setEditedContent: Dispatch<SetStateAction<string>>
  setFiles: Dispatch<SetStateAction<ParsedFile[]>>
  setHoveredBlockId: Dispatch<SetStateAction<string | null>>
  setIsEditing: Dispatch<SetStateAction<boolean>>
  setRightPanelMode: Dispatch<SetStateAction<'blocks' | 'markdown'>>
  updateParsedFile: (id: string, updates: Partial<Omit<ParsedFileData, 'id'>>) => Promise<void>
}

export function useParsingEditorActions({
  activeFile,
  activeMarkdown,
  activeRun,
  addParsedFile,
  countMarkdownHeadings,
  editedContent,
  setActiveBlockId,
  setCopied,
  setEditedContent,
  setFiles,
  setHoveredBlockId,
  setIsEditing,
  setRightPanelMode,
  updateParsedFile,
}: Readonly<UseParsingEditorActionsOptions>) {
  const router = useRouter()

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
    setEditedContent(activeMarkdown)
    setIsEditing(true)
  }, [activeMarkdown, setEditedContent, setIsEditing])

  const handleCancelEdit = useCallback(() => {
    setIsEditing(false)
    setEditedContent('')
  }, [setEditedContent, setIsEditing])

  const handleSaveEdit = useCallback(async () => {
    if (!activeFile) return
    const targetRunId = activeRun?.id ?? activeFile.activeRunId

    setFiles((prev) => applyEditedMarkdown(prev, activeFile.id, targetRunId, editedContent, countMarkdownHeadings))
    setRightPanelMode('markdown')
    setActiveBlockId(null)
    setHoveredBlockId(null)
    setIsEditing(false)

    const libId = (activeFile.libraryId || '').trim()
    if (!libId) return

    try {
      const saved = await parsingApi.updateContent(libId, { markdown_content: editedContent })
      await updateParsedFile(libId, {
        markdownContent: saved.markdown_content || editedContent,
        originalMarkdownContent: saved.original_markdown_content || editedContent,
        status: 'parsed',
        error: undefined,
        parser: getParserLabel(saved.parser_backend || 'auto'),
      })
      toast.success('已保存到服务器')
    } catch (err: unknown) {
      toast.error(formatApiError(err, '保存失败'))
    }
  }, [
    activeFile,
    activeRun,
    countMarkdownHeadings,
    editedContent,
    setActiveBlockId,
    setFiles,
    setHoveredBlockId,
    setIsEditing,
    setRightPanelMode,
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
      })
    } else {
      const libraryId = addParsedFile({
        filename: activeFile.file.name,
        fileType: activeFile.file.name.split('.').pop()?.toLowerCase() || '',
        fileSize: activeFile.file.size,
        markdownContent: activeMarkdown,
        originalMarkdownContent: activeMarkdown,
        parser: activeFile.parserLabel,
        folderId: activeFile.folderId,
        status: 'parsed',
        error: undefined,
      })
      setFiles((prev) => prev.map((file) => (file.id === activeFile.id ? { ...file, libraryId } : file)))
    }

    router.push('/data-governance')
  }, [activeFile, activeMarkdown, addParsedFile, router, setFiles, updateParsedFile])

  return {
    copyMarkdown,
    downloadMarkdown,
    handleCancelEdit,
    handleSaveEdit,
    handleStartEdit,
    handleSubmitToGovernance,
  }
}
