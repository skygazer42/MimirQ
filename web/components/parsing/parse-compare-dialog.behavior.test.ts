// @vitest-environment jsdom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/components/ui/dialog', async () => {
  const React = await import('react')
  return {
    Dialog({ children }: Readonly<{ children?: React.ReactNode }>) {
      return React.createElement('div', { 'data-testid': 'dialog-root' }, children)
    },
    DialogContent({ children }: Readonly<{ children?: React.ReactNode }>) {
      return React.createElement('div', { 'data-testid': 'dialog-content' }, children)
    },
    DialogDescription({ children }: Readonly<{ children?: React.ReactNode }>) {
      return React.createElement('div', null, children)
    },
    DialogHeader({ children }: Readonly<{ children?: React.ReactNode }>) {
      return React.createElement('div', null, children)
    },
    DialogTitle({ children }: Readonly<{ children?: React.ReactNode }>) {
      return React.createElement('div', null, children)
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

vi.mock('@/components/ui/textarea', async () => {
  const React = await import('react')
  return {
    Textarea(props: Readonly<React.TextareaHTMLAttributes<HTMLTextAreaElement>>) {
      return React.createElement('textarea', props)
    },
  }
})

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}))

import { ParseCompareDialog } from './parse-compare-dialog'

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

describe('parse compare dialog behavior', () => {
  it('deduplicates repeated image subtype changes in the structure summary', () => {
    const view = renderComponent(
      React.createElement(ParseCompareDialog, {
        open: true,
        onOpenChange: vi.fn(),
        runs: [
          {
            id: 'base',
            parserBackend: 'deepdoc',
            rawMarkdown: 'base',
            cleanedMarkdown: 'base',
            elements: [
              { id: 'img-1', kind: 'image', page: 1, text: 'Revenue chart', visual_kind: 'diagram' },
              { id: 'img-2', kind: 'image', page: 2, text: 'Revenue chart copy', visual_kind: 'diagram' },
            ],
          },
          {
            id: 'compare',
            parserBackend: 'docling',
            rawMarkdown: 'compare',
            cleanedMarkdown: 'compare',
            elements: [
              { id: 'img-1', kind: 'image', page: 1, text: 'Revenue chart', visual_kind: 'chart' },
              { id: 'img-2', kind: 'image', page: 2, text: 'Revenue chart copy', visual_kind: 'chart' },
            ],
          },
        ],
      })
    )
    rendered.push(view)

    const text = view.container.textContent || ''
    expect(text).toContain('新增图像子类')
    expect(text).toContain('移除图像子类')
    expect(text).toContain('图像子类新增：chart')
    expect(text).toContain('图像子类移除：diagram')
    expect(text.includes('chart · chart')).toBe(false)
    expect(text.includes('diagram · diagram')).toBe(false)
  })
})
