// @vitest-environment jsdom

import React, { act } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { renderHook, waitForAssertion } from '@/test/hook-harness'

import type { ParsingEditSession } from '@/lib/parsing-edit-focus'
import type { ParsedFileData } from '@/store/use-parsed-files-store'

const pushMock = vi.fn()

vi.mock('next-intl', () => ({
  useTranslations: () => (key: string) => key,
}))

vi.mock('@/i18n/navigation', () => ({
  useRouter: () => ({
    push: pushMock,
  }),
}))

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}))

vi.mock('@/lib/api', () => ({
  parsingApi: {
    updateContent: vi.fn(),
  },
}))

import type { ParsedFile, ParseRun } from './parsing-types'
import { parsingApi } from '@/lib/api'
import { useParsingEditorActions } from './use-parsing-editor-actions'

function makeRun(overrides: Partial<ParseRun> = {}): ParseRun {
  return {
    blocks: [
      {
        id: 'block-0',
        positions: [{ bottom: 0.12, left: 0.08, pages: [0], raw: '@@1', right: 0.84, top: 0.08 }],
        text: '# Summary',
      },
      {
        id: 'block-1',
        positions: [{ bottom: 0.24, left: 0.08, pages: [0], raw: '@@2', right: 0.84, top: 0.16 }],
        text: 'First paragraph.',
      },
      {
        id: 'block-2',
        positions: [{ bottom: 0.36, left: 0.08, pages: [0], raw: '@@3', right: 0.84, top: 0.28 }],
        text: 'Second paragraph.',
      },
    ],
    cleanedMarkdown: '# Summary\n\nFirst paragraph.\n\nSecond paragraph.\n\n## Details',
    createdAt: 1_711_111_111_000,
    id: 'run-a',
    parserBackend: 'mineru',
    parserLabel: 'MinerU',
    rawMarkdown: '# Summary\n\nFirst paragraph.\n\nSecond paragraph.\n\n## Details',
    ...overrides,
  }
}

function makeParsedFile(run: ParseRun, overrides: Partial<ParsedFile> = {}): ParsedFile {
  return {
    activeRunId: run.id,
    file: new File(['pdf'], 'report.pdf', { type: 'application/pdf' }),
    folderId: 'folder-1',
    id: 'file-1',
    markdownContent: run.cleanedMarkdown,
    name: 'report.pdf',
    parserBackend: 'mineru',
    parserLabel: 'MinerU',
    runs: [run],
    size: 1024,
    status: 'parsed',
    ...overrides,
  }
}

function createHarness(
  options: Readonly<{
    initialFiles?: ParsedFile[]
    initialLibraryFiles?: ParsedFileData[]
    initialSelectedGovernanceFileIds?: string[]
  }> = {}
) {
  const updateParsedFile = vi.fn().mockResolvedValue(undefined)
  const addParsedFile = vi.fn()

  function useHarness() {
    const [files, setFiles] = React.useState<ParsedFile[]>(options.initialFiles ?? [makeParsedFile(makeRun())])
    const [selectedGovernanceFileIds, setSelectedGovernanceFileIds] = React.useState<Set<string>>(
      () => new Set(options.initialSelectedGovernanceFileIds ?? [])
    )
    const [editedContent, setEditedContent] = React.useState('')
    const [isEditing, setIsEditing] = React.useState(false)
    const [rightPanelMode, setRightPanelMode] = React.useState<'blocks' | 'markdown'>('blocks')
    const [activeBlockId, setActiveBlockId] = React.useState<string | null>('block-2')
    const [hoveredBlockId, setHoveredBlockId] = React.useState<string | null>(null)
    const [copied, setCopied] = React.useState(false)
    const [editSession, setEditSession] = React.useState<ParsingEditSession | null>(null)
    const activeFile = files[0] ?? null
    const activeRun = activeFile?.runs?.[0] ?? null
    const activeMarkdown = activeRun?.cleanedMarkdown ?? activeFile?.markdownContent ?? ''

    const actions = useParsingEditorActions({
      activeBlockId,
      activeBlocksWithPositions: activeRun?.blocks ?? [],
      activeFile,
      activeMarkdown,
      activeRun,
      addParsedFile,
      countMarkdownHeadings: (markdown: string) => markdown.split('\n').filter((line) => /^#{1,6}\s/.test(line)).length,
      editSession,
      editedContent,
      files,
      libraryFiles: options.initialLibraryFiles ?? [],
      selectedGovernanceFileIds,
      setActiveBlockId,
      setCopied,
      setEditedContent,
      setEditSession,
      setFiles,
      setHoveredBlockId,
      setIsEditing,
      setRightPanelMode,
      setSelectedGovernanceFileIds,
      updateParsedFile,
    })

    return {
      ...actions,
      activeBlockId,
      copied,
      editSession,
      editedContent,
      files,
      hoveredBlockId,
      isEditing,
      rightPanelMode,
      selectedGovernanceFileIds,
      setEditedContent,
      updateParsedFile,
    }
  }

  return {
    addParsedFile,
    updateParsedFile,
    useHarness,
  }
}

describe('useParsingEditorActions behavior', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(parsingApi.updateContent).mockResolvedValue({
      document_id: 'library-1',
      elements: [],
      markdown_content: '# Summary\n\nFirst paragraph.\n\nUpdated paragraph.\n\n## Details',
      original_markdown_content: '# Summary\n\nFirst paragraph.\n\nUpdated paragraph.\n\n## Details',
      parser_backend: 'mineru',
      pdf_quality: {
        format_consistency_score: 1,
        is_scanned: false,
        page_count: 1,
        score: 1,
        table_quality_score: 1,
        text_quality_score: 1,
      },
      quality_gate: { grade: 'pass', reasons: [], evidence: {} },
    })
  })

  it('starts editing from only the selected layout block content', () => {
    const { useHarness } = createHarness()
    const hook = renderHook(() => useHarness())

    act(() => {
      hook.result.current.handleStartEdit()
    })

    expect(hook.result.current.isEditing).toBe(true)
    expect(hook.result.current.editedContent).toBe('Second paragraph.')
    expect(hook.result.current.editSession).toEqual(
      expect.objectContaining({
        mode: 'block',
        blockId: 'block-2',
      })
    )

    hook.unmount()
  })

  it('saves a block edit by patching only that block back into the full markdown', async () => {
    const { useHarness } = createHarness()
    const hook = renderHook(() => useHarness())

    act(() => {
      hook.result.current.handleStartEdit()
    })

    act(() => {
      hook.result.current.setEditedContent('Updated paragraph.')
    })

    await act(async () => {
      await hook.result.current.handleSaveEdit()
    })

    await waitForAssertion(() => {
      expect(hook.result.current.files[0]?.markdownContent).toBe(
        '# Summary\n\nFirst paragraph.\n\nUpdated paragraph.\n\n## Details'
      )
      expect(hook.result.current.files[0]?.governanceStatus).toBe('ready')
    })

    expect(hook.result.current.isEditing).toBe(false)
    expect(hook.result.current.rightPanelMode).toBe('markdown')
    expect(hook.result.current.activeBlockId).toBeNull()
    expect(hook.result.current.editSession).toBeNull()

    hook.unmount()
  })

  it('saves a parsed library document as ready for batch governance submission', async () => {
    const run = makeRun()
    const { updateParsedFile, useHarness } = createHarness({
      initialFiles: [makeParsedFile(run, { libraryId: 'library-1' })],
    })
    const hook = renderHook(() => useHarness())

    act(() => {
      hook.result.current.handleStartEdit()
    })

    act(() => {
      hook.result.current.setEditedContent('Updated paragraph.')
    })

    await act(async () => {
      await hook.result.current.handleSaveEdit()
    })

    expect(updateParsedFile).toHaveBeenCalledWith(
      'library-1',
      expect.objectContaining({
        governanceStatus: 'ready',
        status: 'parsed',
      })
    )

    hook.unmount()
  })

  it('saves the current markdown without blanking content when no edit session is active', async () => {
    const run = makeRun()
    vi.mocked(parsingApi.updateContent).mockResolvedValueOnce({
      document_id: 'library-1',
      elements: [],
      markdown_content: run.cleanedMarkdown,
      original_markdown_content: run.cleanedMarkdown,
      parser_backend: 'mineru',
      pdf_quality: null,
      quality_gate: null,
    })
    const { updateParsedFile, useHarness } = createHarness({
      initialFiles: [makeParsedFile(run, { libraryId: 'library-1' })],
    })
    const hook = renderHook(() => useHarness())

    await act(async () => {
      await hook.result.current.handleSaveEdit()
    })

    expect(parsingApi.updateContent).toHaveBeenCalledWith('library-1', {
      markdown_content: run.cleanedMarkdown,
    })
    expect(updateParsedFile).toHaveBeenCalledWith(
      'library-1',
      expect.objectContaining({
        markdownContent: run.cleanedMarkdown,
        governanceStatus: 'ready',
        status: 'parsed',
      })
    )
    expect(hook.result.current.files[0]?.markdownContent).toBe(run.cleanedMarkdown)

    hook.unmount()
  })

  it('submits selected ready documents to governance in one batch', async () => {
    const run = makeRun()
    const { updateParsedFile, useHarness } = createHarness({
      initialFiles: [
        makeParsedFile(run, {
          governanceStatus: 'ready',
          id: 'queue-file-1',
          libraryId: 'library-1',
        }),
      ],
      initialLibraryFiles: [
        {
          fileSize: 128,
          fileType: 'md',
          filename: 'stored.md',
          governanceStatus: 'ready',
          id: 'library-2',
          markdownContent: '# Stored',
          parsedAt: '2024-01-01T00:00:00.000Z',
          parser: 'Markdown',
          status: 'parsed',
        },
      ],
      initialSelectedGovernanceFileIds: ['queue-file-1', 'library-2'],
    })
    const hook = renderHook(() => useHarness())

    await act(async () => {
      await hook.result.current.handleSubmitSelectedToGovernance()
    })

    expect(updateParsedFile).toHaveBeenCalledWith(
      'library-1',
      expect.objectContaining({
        governanceStatus: 'submitted',
        markdownContent: expect.stringContaining('# Summary'),
        status: 'parsed',
      })
    )
    expect(updateParsedFile).toHaveBeenCalledWith(
      'library-2',
      expect.objectContaining({
        governanceStatus: 'submitted',
        markdownContent: '# Stored',
        status: 'parsed',
      })
    )
    expect(hook.result.current.selectedGovernanceFileIds.size).toBe(0)
    expect(pushMock).toHaveBeenCalledWith('/data-governance')

    hook.unmount()
  })
})
