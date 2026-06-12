// @vitest-environment jsdom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ParsedFileData } from '@/store/use-parsed-files-store'

import { ParsingLibraryPreviewPane } from './parsing-library-preview-pane'

vi.mock('next-intl', () => ({
  useTranslations:
    (scope: string) =>
    (key: string) => {
      const messages: Record<string, string> = {
        'ParsingWorkbench.libraryPreview.parserLabel': '解析方式',
        'ParsingWorkbench.libraryPreview.startParsing': '开始解析',
        'ParsingWorkbench.libraryPreview.startParsingTitle': '使用当前解析器开始解析该文档',
        'ParsingWorkbench.libraryPreview.restoreSource': '恢复源文',
        'ParsingWorkbench.libraryPreview.restoreSourceTitle': '从服务器下载源文件到队列',
        'ParsingWorkbench.libraryPreview.reupload': '重新上传',
        'ParsingWorkbench.libraryPreview.reuploadTitle': '重新上传源文件',
        'ParsingWorkbench.libraryPreview.moreActions': '更多操作',
        'ParsingWorkbench.libraryPreview.more': '更多',
        'ParsingWorkbench.libraryPreview.copiedFilename': '已复制文件名',
        'ParsingWorkbench.libraryPreview.copyFailed': '复制失败',
        'ParsingWorkbench.libraryPreview.copyFilename': '复制文件名',
        'ParsingWorkbench.libraryPreview.emptyTitle': '暂无可展示的解析内容',
        'ParsingWorkbench.libraryPreview.emptyDescription': '若该文件还未解析，或内容未缓存，请重新选择文件并解析。',
        'Common.close': '关闭',
      }
      return messages[`${scope}.${key}`] || key
    },
}))

vi.mock('@/components/business/parser-dropdown', async () => {
  const React = await import('react')

  return {
    ParserDropdown({ onChange, value }: Readonly<{ onChange?: (value: string) => void; value?: string }>) {
      return React.createElement(
        'button',
        {
          'data-testid': 'parser-dropdown',
          'data-value': value || '',
          onClick: () => onChange?.('mineru'),
          type: 'button',
        },
        `parser:${value || ''}`
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

vi.mock('@/components/parsing/parsing-right-panel', async () => {
  const React = await import('react')
  return {
    ParsingRightPanel({ children }: Readonly<{ children?: React.ReactNode }>) {
      return React.createElement('div', { 'data-testid': 'right-panel' }, children)
    },
  }
})

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

function findButtonByText(root: ParentNode, text: string): HTMLButtonElement | null {
  return Array.from(root.querySelectorAll<HTMLButtonElement>('button')).find((button) => button.textContent?.includes(text)) ?? null
}

function makeKnowledgeFile(overrides: Partial<ParsedFileData> = {}): ParsedFileData {
  return {
    id: 'doc-1',
    filename: 'ingestion-audit-report.html',
    fileSize: 2400,
    fileType: 'html',
    markdownContent: '',
    originalMarkdownContent: '',
    parsedAt: new Date().toISOString(),
    parser: 'pandoc（Office/HTML）',
    parserBackend: 'pandoc',
    source: 'knowledge_base',
    status: 'pending',
    ...overrides,
  }
}

describe('ParsingLibraryPreviewPane behavior', () => {
  afterEach(() => {
    vi.clearAllMocks()
    document.body.innerHTML = ''
  })

  it('lets pending knowledge-base documents choose a parser and start processing', () => {
    const onReprocessKnowledgeFile = vi.fn()
    const onUpdateParser = vi.fn()
    const view = renderComponent(
      React.createElement(ParsingLibraryPreviewPane, {
        activeMarkdown: '',
        defaultParserBackend: 'auto',
        file: makeKnowledgeFile(),
        folderName: '根目录',
        folderPathLabel: '根目录',
        onClose: vi.fn(),
        onReprocessKnowledgeFile,
        onRequestRebind: vi.fn(),
        onRestoreSource: vi.fn(),
        onUpdateParser,
        sourceStatus: 'available',
        statusBadge: { cls: '', label: '待解析' },
      })
    )

    expect(view.container.querySelector('[data-testid="parser-dropdown"]')?.getAttribute('data-value')).toBe('pandoc')

    const startButton = findButtonByText(view.container, '开始解析')
    expect(startButton).not.toBeNull()

    act(() => {
      startButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(onReprocessKnowledgeFile).toHaveBeenCalledWith('pandoc')
    view.unmount()
  })
})
