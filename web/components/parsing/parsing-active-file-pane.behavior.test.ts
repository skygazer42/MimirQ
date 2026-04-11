// @vitest-environment jsdom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ParsedFile, ParseRun } from './parsing-types'
import { waitForAssertion } from '@/test/hook-harness'

const parsingApiExtractMock = vi.hoisted(() => vi.fn())

vi.mock('@/lib/api', () => ({
  parsingApi: {
    extract: parsingApiExtractMock,
  },
}))

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
      onClickBlockId,
      onHoverBlockId,
    }: Readonly<{
      activeBlockIds?: string[] | null
      hoveredBlockIds?: string[] | null
      onClickBlockId?: (blockId: string) => void
      onHoverBlockId?: (blockId: string | null) => void
    }>) {
      return React.createElement(
        'div',
        {
          'data-active-ids': (activeBlockIds || []).join(','),
          'data-hovered-ids': (hoveredBlockIds || []).join(','),
          'data-testid': 'pdf-viewer',
        },
        React.createElement(
          'button',
          {
            'data-testid': 'pdf-viewer-select-block',
            onClick: () => onClickBlockId?.('pdf-block-1'),
            onMouseEnter: () => onHoverBlockId?.('pdf-block-1'),
            onMouseLeave: () => onHoverBlockId?.(null),
            type: 'button',
          },
          'select-block'
        )
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
    libraryId: 'library-1',
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
    activeElements: [],
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

  it('renders normalized element summary chips for specialty parse elements', async () => {
    const view = renderComponent(
      React.createElement(
        ParsingActiveFilePane,
        makePaneProps({
          activeElements: [
            { id: 'seal-1', kind: 'seal', page: 2, text: '杭州测试科技有限公司', confidence: 0.97 },
            { id: 'eq-1', kind: 'equation', page: 1, text: 'E = mc^2' },
            { id: 'eq-2', kind: 'equation', page: 1, text: 'F = ma' },
          ],
        })
      )
    )

    await waitForAssertion(() => {
      expect(view.container.textContent).toContain('结构元素')
      expect(view.container.textContent).toContain('印章')
      expect(view.container.textContent).toContain('公式')
      expect(view.container.textContent).toContain('2')
      expect(view.container.textContent).toContain('主印章')
      expect(view.container.textContent).toContain('杭州测试科技有限公司')
      expect(view.container.textContent).toContain('公式样例')
      expect(view.container.textContent).toContain('E = mc^2')
    })

    view.unmount()
  })

  it('renders image subtype summary chips when visual kinds are present', async () => {
    const view = renderComponent(
      React.createElement(
        ParsingActiveFilePane,
        makePaneProps({
          activeElements: [
            { id: 'img-1', kind: 'image', page: 1, text: 'Revenue growth chart', visual_kind: 'chart' },
            { id: 'img-2', kind: 'image', page: 2, text: '扫码二维码', visual_kind: 'qr' },
          ],
        })
      )
    )

    await waitForAssertion(() => {
      expect(view.container.textContent).toContain('图片子类')
      expect(view.container.textContent).toContain('chart×1')
      expect(view.container.textContent).toContain('qr×1')
    })

    view.unmount()
  })

  it('runs extraction from the inline workbench panel and renders evidence details', async () => {
    parsingApiExtractMock.mockResolvedValueOnce({
      document_id: 'library-1',
      mode: 'schema',
      result: {
        company_name: {
          value: '杭州测试科技有限公司',
          confidence: 0.97,
          strategy: 'element_match',
          evidence: [
            {
              element_id: 'seal-1',
              kind: 'seal',
              page: 2,
              pages: [2, 3],
              visual_kind: 'stamp',
              bbox: { x0: 10, y0: 20, x1: 60, y1: 70 },
              text: '杭州测试科技有限公司',
              score: 0.97,
            },
          ],
        },
      },
    })

    const view = renderComponent(
      React.createElement(
        ParsingActiveFilePane,
        makePaneProps({
          isPdf: true,
          activeElements: [{ id: 'seal-1', kind: 'seal', page: 2, pages: [2, 3], text: '杭州测试科技有限公司', confidence: 0.97 }],
        })
      )
    )

    const runButton = findButtonByText(view.container, '运行抽取')
    expect(runButton).not.toBeNull()

    act(() => {
      runButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    await waitForAssertion(() => {
      expect(parsingApiExtractMock).toHaveBeenCalledTimes(1)
      expect(view.container.textContent).toContain('抽取结果')
      expect(view.container.textContent).toContain('company_name')
      expect(view.container.textContent).toContain('杭州测试科技有限公司')
      expect(view.container.querySelector('[data-testid="extract-evidence-button"]')).not.toBeNull()
    })

    const evidenceButton = view.container.querySelector('[data-testid="extract-evidence-button"]')
    expect(evidenceButton).not.toBeNull()

    act(() => {
      evidenceButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    await waitForAssertion(() => {
      expect(view.container.textContent).toContain('证据定位')
      expect(view.container.textContent).toContain('seal-1')
      expect(view.container.textContent).toContain('stamp')
      expect(view.container.textContent).toContain('跨页 2-3')
      expect(view.container.textContent).toContain('10,20,60,70')
      const pdfViewer = view.container.querySelector('[data-testid="pdf-viewer"]')
      expect(pdfViewer?.getAttribute('data-active-ids')).toContain('extract-evidence:seal-1')
    })

    view.unmount()
  })

  it('filters and selects structured elements from the inline elements panel', async () => {
    const view = renderComponent(
      React.createElement(
        ParsingActiveFilePane,
        makePaneProps({
          isPdf: true,
          activeElements: [
            { id: 'seal-1', kind: 'seal', page: 2, text: '杭州测试科技有限公司', confidence: 0.97, bbox: { x0: 10, y0: 20, x1: 60, y1: 70 } },
            { id: 'eq-1', kind: 'equation', page: 1, text: 'E = mc^2', confidence: 0.88, bbox: { x0: 1, y0: 2, x1: 3, y1: 4 } },
          ],
        })
      )
    )

    const sealFilter = findButtonByText(view.container, '印章')
    expect(sealFilter).not.toBeNull()

    act(() => {
      sealFilter?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    await waitForAssertion(() => {
      expect(view.container.textContent).toContain('结构元素列表')
      expect(view.container.textContent).toContain('杭州测试科技有限公司')
    })

    const sealItem = findButtonByText(view.container, 'seal-1')
    expect(sealItem).not.toBeNull()

    act(() => {
      sealItem?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    await waitForAssertion(() => {
      expect(view.container.textContent).toContain('证据定位')
      expect(view.container.textContent).toContain('seal-1')
      const pdfViewer = view.container.querySelector('[data-testid="pdf-viewer"]')
      expect(pdfViewer?.getAttribute('data-active-ids')).toContain('extract-evidence:seal-1')
    })

    view.unmount()
  })

  it('lets equation elements from parser-native payloads jump into evidence positioning', async () => {
    const view = renderComponent(
      React.createElement(
        ParsingActiveFilePane,
        makePaneProps({
          isPdf: true,
          activeElements: [
            {
              id: 'equation:2:0',
              kind: 'equation',
              page: 2,
              text: 'E = mc^2@@2\t20\t80\t30\t90##',
              confidence: 0.88,
              bbox: { x0: 20, y0: 30, x1: 80, y1: 90 },
              attributes: { source_content_type: 'equation' },
            },
          ],
        })
      )
    )

    const equationFilter = findButtonByText(view.container, '公式')
    expect(equationFilter).not.toBeNull()

    act(() => {
      equationFilter?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    await waitForAssertion(() => {
      expect(view.container.textContent).toContain('equation')
      expect(view.container.textContent).toContain('equation:2:0')
      expect(view.container.textContent).toContain('20,30,80,90')
      expect(view.container.textContent).toContain('0.88')
    })

    const equationItem = findButtonByText(view.container, 'equation:2:0')
    expect(equationItem).not.toBeNull()

    act(() => {
      equationItem?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    await waitForAssertion(() => {
      expect(view.container.textContent).toContain('证据定位')
      expect(view.container.textContent).toContain('equation:2:0')
      const pdfViewer = view.container.querySelector('[data-testid="pdf-viewer"]')
      expect(pdfViewer?.getAttribute('data-active-ids')).toContain('extract-evidence:equation:2:0')
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
      expect((textarea as HTMLTextAreaElement).selectionEnd).toBe(markdown.indexOf('Second paragraph.'))
    })

    view.unmount()
  })

  it('forwards pdf overlay clicks into the active block selection state', async () => {
    const onActiveBlockIdChange = vi.fn()
    const onHoveredBlockIdChange = vi.fn()
    const view = renderComponent(
      React.createElement(
        ParsingActiveFilePane,
        makePaneProps({
          activeBlocksWithPositions: [
            {
              id: 'pdf-block-1',
              positions: [{ bottom: 0.22, left: 0.08, pages: [0], raw: '@@1', right: 0.84, top: 0.12 }],
              text: 'Paragraph',
            },
          ],
          isPdf: true,
          onActiveBlockIdChange,
          onHoveredBlockIdChange,
          rightPanelMode: 'markdown',
        })
      )
    )

    await waitForAssertion(() => {
      expect(view.container.querySelector('[data-testid="pdf-viewer-select-block"]')).not.toBeNull()
    })

    const viewerSelectButton = view.container.querySelector('[data-testid="pdf-viewer-select-block"]')

    act(() => {
      viewerSelectButton?.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }))
      viewerSelectButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      viewerSelectButton?.dispatchEvent(new MouseEvent('mouseleave', { bubbles: true }))
    })

    expect(onActiveBlockIdChange).toHaveBeenCalledWith('pdf-block-1')

    view.unmount()
  })
})
