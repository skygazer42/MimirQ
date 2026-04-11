// @vitest-environment jsdom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('next-intl', () => ({
  useTranslations: () => (key: string, values?: Record<string, unknown>) => {
    if (key === 'mobileInspector.pageLabel') {
      return `页 ${String(values?.page ?? '')}`
    }
    return key
  },
}))

vi.mock('@/components/markdown/markdown-toc', async () => {
  const React = await import('react')
  return {
    MarkdownToc() {
      return React.createElement('div', { 'data-testid': 'markdown-toc' }, 'toc')
    },
  }
})

vi.mock('@/components/parsing/parsing-extract-panel', async () => {
  const React = await import('react')
  return {
    ParsingExtractPanel() {
      return React.createElement('div', { 'data-testid': 'extract-panel' }, 'extract-panel')
    },
  }
})

vi.mock('@/components/ui/button', async () => {
  const React = await import('react')
  return {
    Button({ children, ...props }: Readonly<React.ButtonHTMLAttributes<HTMLButtonElement>>) {
      return React.createElement('button', props, children)
    },
  }
})

import { ParsingMobileInspectorContent } from './parsing-mobile-inspector-content'

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

const rendered: Array<ReturnType<typeof renderComponent>> = []

afterEach(() => {
  while (rendered.length > 0) {
    rendered.pop()?.unmount()
  }
})

describe('parsing mobile inspector content behavior', () => {
  it('shows image visual_kind chips and cross-page labels in the element list', () => {
    const view = renderComponent(
      React.createElement(ParsingMobileInspectorContent, {
        documentId: 'doc-1',
        activeMarkdown: '# Parsed',
        rightPanelMode: 'markdown',
        previewMode: 'rendered',
        activeBlocksWithPositions: [],
        activeBlockId: null,
        activeElements: [
          {
            id: 'image:1:0',
            kind: 'image',
            page: 2,
            pages: [2, 3],
            text: 'Revenue growth chart',
            visual_kind: 'chart',
          },
        ],
        onRightPanelModeChange: vi.fn(),
        onPreviewModeChange: vi.fn(),
        onSelectBlock: vi.fn(),
        onSelectElement: vi.fn(),
        onSelectEvidence: vi.fn(),
        onCopyMarkdown: vi.fn(),
        onDownloadMarkdown: vi.fn(),
      })
    )
    rendered.push(view)

    const text = view.container.textContent || ''
    expect(text).toContain('chart')
    expect(text).toContain('页 2-3')
    expect(text).toContain('Revenue growth chart')
  })
})
