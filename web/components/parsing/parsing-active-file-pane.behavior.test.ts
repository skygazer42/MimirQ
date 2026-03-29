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
})
