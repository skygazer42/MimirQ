// @vitest-environment jsdom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ParsedFile, ParseRun } from './parsing-types'
import { waitForAssertion } from '@/test/hook-harness'

vi.mock('next/dynamic', async () => {
  const React = await import('react')

  return {
    default(
      loader: () => Promise<unknown>,
      options?: Readonly<{ loading?: (props: Record<string, unknown>) => React.ReactNode }>
    ) {
      return function DynamicComponent(props: Record<string, unknown>) {
        const [Loaded, setLoaded] = React.useState<React.ComponentType<any> | null>(null)

        React.useEffect(() => {
          let active = true

          void (async () => {
            await new Promise((resolve) => globalThis.setTimeout(resolve, 0))
            const resolved = await loader()
            const component =
              typeof resolved === 'function'
                ? resolved
                : (resolved as { default?: React.ComponentType<any> }).default ?? null

            if (active && component) {
              setLoaded(() => component as React.ComponentType<any>)
            }
          })()

          return () => {
            active = false
          }
        }, [])

        if (!Loaded) return options?.loading?.(props) ?? null
        return React.createElement(Loaded, props)
      }
    },
  }
})

vi.mock('@/components/parsing/parse-compare-dialog', async () => {
  const React = await import('react')

  return {
    ParseCompareDialog({
      defaultBaseRunId,
      open,
      runs,
    }: Readonly<{ defaultBaseRunId?: string | null; open: boolean; runs: ParseRun[] }>) {
      return React.createElement(
        'div',
        {
          'data-default-base': defaultBaseRunId ?? '',
          'data-open': String(open),
          'data-run-count': String(runs.length),
          'data-testid': 'parse-compare-dialog',
        },
        open ? 'dialog-open' : 'dialog-closed'
      )
    },
  }
})

vi.mock('@/components/markdown/markdown-renderer', async () => {
  const React = await import('react')

  return {
    MarkdownRenderer({ markdown }: Readonly<{ markdown: string }>) {
      return React.createElement('div', { 'data-testid': 'markdown-renderer' }, markdown)
    },
  }
})

vi.mock('@/components/markdown/markdown-toc', async () => {
  const React = await import('react')

  return {
    MarkdownToc() {
      return React.createElement('div', { 'data-testid': 'markdown-toc' }, 'toc')
    },
  }
})

vi.mock('@/components/business/parser-dropdown', async () => {
  const React = await import('react')

  return {
    ParserDropdown() {
      return React.createElement('div', { 'data-testid': 'parser-dropdown' }, 'parser-dropdown')
    },
  }
})

vi.mock('@/components/parsing/parsing-right-panel', async () => {
  const React = await import('react')

  return {
    ParsingRightPanel({
      children,
      className,
    }: Readonly<{ children?: React.ReactNode; className?: string }>) {
      return React.createElement('div', { className, 'data-testid': 'parsing-right-panel' }, children)
    },
  }
})

vi.mock('@/components/parsing/pdf-viewer', async () => {
  const React = await import('react')

  return {
    PdfViewer({
      activeBlockIds,
      hoveredBlockIds,
    }: Readonly<{ activeBlockIds?: string[] | null; hoveredBlockIds?: string[] | null }>) {
      return React.createElement(
        'div',
        {
          'data-active-ids': (activeBlockIds || []).join(','),
          'data-hovered-ids': (hoveredBlockIds || []).join(','),
          'data-testid': 'pdf-viewer',
        },
        'pdf-viewer'
      )
    },
  }
})

vi.mock('@/components/ui/button', async () => {
  const React = await import('react')

  return {
    Button({
      children,
      size: _size,
      variant: _variant,
      ...props
    }: Readonly<React.ButtonHTMLAttributes<HTMLButtonElement> & { size?: string; variant?: string }>) {
      return React.createElement('button', props, children)
    },
  }
})

vi.mock('@/components/ui/skeleton', async () => {
  const React = await import('react')

  return {
    Skeleton(props: Readonly<Record<string, unknown>>) {
      return React.createElement('div', props)
    },
  }
})

vi.mock('@/components/ui/stats-card', async () => {
  const React = await import('react')

  return {
    StatCard({ label, value }: Readonly<{ label: string; value: React.ReactNode }>) {
      return React.createElement('div', { 'data-testid': 'stat-card' }, `${label}:${value ?? ''}`)
    },
    StatsGrid({ children }: Readonly<{ children?: React.ReactNode }>) {
      return React.createElement('div', { 'data-testid': 'stats-grid' }, children)
    },
  }
})

import { ParsingActiveFilePane } from './parsing-active-file-pane'

function renderComponent(element: React.ReactElement) {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)

  act(() => {
    root.render(element)
  })

  return {
    container,
    unmount() {
      act(() => {
        root.unmount()
      })
      container.remove()
    },
  }
}

function findButtonByText(container: HTMLElement, text: string) {
  return Array.from(container.querySelectorAll('button')).find((button) => button.textContent?.includes(text)) ?? null
}

function makeRun(overrides: Partial<ParseRun> = {}): ParseRun {
  return {
    blocks: [],
    cleanedMarkdown: '# cleaned',
    createdAt: 1_711_111_111_000,
    id: 'run-a',
    parserBackend: 'marker',
    parserLabel: 'Marker',
    rawMarkdown: '# raw',
    ...overrides,
  }
}

function makeParsedFile(runs: ParseRun[]): ParsedFile {
  return {
    activeRunId: runs[0]?.id,
    file: new File(['# report'], 'report.md', { type: 'text/markdown' }),
    folderId: 'folder-1',
    id: 'file-1',
    markdownContent: runs[0]?.cleanedMarkdown ?? '',
    name: 'report.md',
    parserBackend: 'marker',
    parserLabel: 'Marker',
    runs,
    size: 128,
    status: 'parsed',
  }
}

function makePaneProps(overrides: Partial<React.ComponentProps<typeof ParsingActiveFilePane>> = {}) {
  const run = makeRun()
  const file = makeParsedFile([run])

  return {
    activeBlockId: null,
    activeBlocksWithPositions: [],
    activeFile: file,
    activeMarkdown: run.cleanedMarkdown,
    activePdfQuality: null,
    activeQualityGate: null,
    activeRun: run,
    copied: false,
    editedContent: '',
    hoveredBlockId: null,
    isEditing: false,
    isPdf: false,
    onActiveBlockIdChange: vi.fn(),
    onCancelEdit: vi.fn(),
    onCopyMarkdown: vi.fn(),
    onDownloadMarkdown: vi.fn(),
    onEditedContentChange: vi.fn(),
    onHoveredBlockIdChange: vi.fn(),
    onParseFile: vi.fn(),
    onPreviewModeChange: vi.fn(),
    onRightPanelModeChange: vi.fn(),
    onSaveEdit: vi.fn(),
    onSelectRun: vi.fn(),
    onSetQueueFileParserBackend: vi.fn(),
    onStartEdit: vi.fn(),
    onSubmitToGovernance: vi.fn(),
    pdfPreviewResetToken: 0,
    previewMode: 'rendered' as const,
    rightPanelMode: 'markdown' as const,
    tocEnabled: false,
    ...overrides,
  }
}

describe('ParsingActiveFilePane lazy compare interactions', () => {
  afterEach(() => {
    vi.clearAllMocks()
    document.body.innerHTML = ''
  })

  it('opens the parse compare dialog after the lazy chunk resolves', async () => {
    const runs = [
      makeRun({ id: 'run-a', parserLabel: 'Marker' }),
      makeRun({ id: 'run-b', parserBackend: 'docling', parserLabel: 'Docling' }),
    ]
    const activeFile = makeParsedFile(runs)
    const activeRun = runs[0]
    const view = renderComponent(
      React.createElement(ParsingActiveFilePane, {
        activeBlockId: null,
        activeBlocksWithPositions: [],
        activeFile,
        activeMarkdown: activeRun.cleanedMarkdown,
        activePdfQuality: null,
        activeQualityGate: null,
        activeRun,
        copied: false,
        editedContent: '',
        hoveredBlockId: null,
        isEditing: false,
        isPdf: false,
        onActiveBlockIdChange: vi.fn(),
        onCancelEdit: vi.fn(),
        onCopyMarkdown: vi.fn(),
        onDownloadMarkdown: vi.fn(),
        onEditedContentChange: vi.fn(),
        onHoveredBlockIdChange: vi.fn(),
        onParseFile: vi.fn(),
        pdfPreviewResetToken: 0,
        onPreviewModeChange: vi.fn(),
        onRightPanelModeChange: vi.fn(),
        onSaveEdit: vi.fn(),
        onSelectRun: vi.fn(),
        onSetQueueFileParserBackend: vi.fn(),
        onStartEdit: vi.fn(),
        onSubmitToGovernance: vi.fn(),
        previewMode: 'rendered',
        rightPanelMode: 'markdown',
        tocEnabled: false,
      })
    )

    await waitForAssertion(() => {
      const dialog = view.container.querySelector('[data-testid="parse-compare-dialog"]')
      expect(dialog).not.toBeNull()
      expect(dialog?.getAttribute('data-open')).toBe('false')
    })

    const compareButton = findButtonByText(view.container, '对比')
    expect(compareButton).not.toBeNull()

    act(() => {
      compareButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    await waitForAssertion(() => {
      const dialog = view.container.querySelector('[data-testid="parse-compare-dialog"]')
      expect(dialog?.getAttribute('data-open')).toBe('true')
      expect(dialog?.getAttribute('data-run-count')).toBe('2')
      expect(dialog?.getAttribute('data-default-base')).toBe('run-a')
    })

    view.unmount()
  })

  it('renders a denser layout review panel with kind labels and a pdf legend', async () => {
    const onActiveBlockIdChange = vi.fn()

    const view = renderComponent(
      React.createElement(
        ParsingActiveFilePane,
        makePaneProps({
          activeBlocksWithPositions: [
            {
              id: 'block-1',
              positions: [{ bottom: 0.22, left: 0.08, pages: [0], raw: '@@', right: 0.84, top: 0.12 }],
              text: '# Summary',
            },
            {
              id: 'block-2',
              positions: [{ bottom: 0.68, left: 0.12, pages: [1], raw: '@@', right: 0.72, top: 0.31 }],
              text: '| Name | Score |\n| --- | --- |\n| Alice | 98 |',
            },
          ],
          isPdf: true,
          onActiveBlockIdChange,
          rightPanelMode: 'blocks',
        })
      )
    )

    expect(view.container.textContent).toContain('版面图例')
    expect(view.container.textContent).toContain('标题')
    expect(view.container.textContent).toContain('表格')
    expect(view.container.textContent).toContain('点击右侧片段可定位到左侧 PDF 原页')

    const cards = Array.from(view.container.querySelectorAll('button')).filter((button) =>
      button.textContent?.includes('页')
    )
    expect(cards.some((button) => button.textContent?.includes('字'))).toBe(true)

    act(() => {
      cards[0]?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(onActiveBlockIdChange).toHaveBeenCalledWith('block-1')
    await waitForAssertion(() => {
      expect(view.container.querySelector('[data-testid="pdf-viewer"]')).not.toBeNull()
    })

    view.unmount()
  })

  it('breaks a multi-line positioned block into finer layout rows for pdf-side navigation', () => {
    const onActiveBlockIdChange = vi.fn()

    const view = renderComponent(
      React.createElement(
        ParsingActiveFilePane,
        makePaneProps({
          activeBlocksWithPositions: [
            {
              id: 'toc',
              positions: [
                { bottom: 0.12, left: 0.08, pages: [0], raw: '@@1', right: 0.84, top: 0.08 },
                { bottom: 0.18, left: 0.08, pages: [0], raw: '@@2', right: 0.84, top: 0.14 },
                { bottom: 0.24, left: 0.08, pages: [0], raw: '@@3', right: 0.84, top: 0.2 },
              ],
              text: '前言\n1 范围\n2 规范性引用文件',
            },
          ],
          isPdf: true,
          onActiveBlockIdChange,
          rightPanelMode: 'blocks',
        })
      )
    )

    const layoutRows = Array.from(view.container.querySelectorAll('button')).filter((button) =>
      button.textContent?.includes('页 1')
    )

    expect(layoutRows).toHaveLength(3)

    act(() => {
      layoutRows[1]?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(onActiveBlockIdChange).toHaveBeenCalledWith('toc:1')

    view.unmount()
  })

  it('moves the edit cursor to the active layout block instead of resetting to the top', async () => {
    const markdown = '# Summary\n\nFirst paragraph.\n\nSecond paragraph.\n\n## Details'
    const view = renderComponent(
      React.createElement(
        ParsingActiveFilePane,
        makePaneProps({
          activeBlockId: 'block-2',
          activeBlocksWithPositions: [
            {
              id: 'block-0',
              positions: [{ bottom: 0.12, left: 0.08, pages: [0], raw: '@@1', right: 0.84, top: 0.08 }],
              text: '# Summary',
            },
            {
              id: 'block-1',
              positions: [{ bottom: 0.22, left: 0.08, pages: [0], raw: '@@2', right: 0.84, top: 0.16 }],
              text: 'First paragraph.',
            },
            {
              id: 'block-2',
              positions: [{ bottom: 0.34, left: 0.08, pages: [0], raw: '@@3', right: 0.84, top: 0.24 }],
              text: 'Second paragraph.',
            },
          ],
          activeMarkdown: markdown,
          editedContent: markdown,
          isEditing: true,
        })
      )
    )

    await waitForAssertion(() => {
      const textarea = view.container.querySelector('textarea')
      expect(textarea).not.toBeNull()
      expect((textarea as HTMLTextAreaElement).selectionStart).toBe(markdown.indexOf('Second paragraph.'))
      expect((textarea as HTMLTextAreaElement).selectionEnd).toBe(
        markdown.indexOf('Second paragraph.') + 'Second paragraph.'.length
      )
    })

    view.unmount()
  })
})
