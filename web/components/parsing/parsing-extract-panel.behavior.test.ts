// @vitest-environment jsdom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'

import { ParsingExtractPanel } from './parsing-extract-panel'

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

describe('parsing extract panel behavior', () => {
  it('supports collapsing and expanding the extract panel body', () => {
    const view = renderComponent(
      React.createElement(ParsingExtractPanel, {
        documentId: 'doc-collapse',
        activeElements: [],
      })
    )
    rendered.push(view)

    expect(view.container.textContent).toContain('字段名')
    const toggleButton = Array.from(view.container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('收起')
    )
    expect(toggleButton).not.toBeNull()

    act(() => {
      toggleButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(view.container.textContent).not.toContain('字段名')
    expect(view.container.textContent).toContain('展开')

    const expandButton = Array.from(view.container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('展开')
    )
    expect(expandButton).not.toBeNull()

    act(() => {
      expandButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(view.container.textContent).toContain('字段名')
    expect(view.container.textContent).toContain('收起')
  })

  it('shows visual kind choices for image extraction and hides them for non-image kinds', () => {
    const view = renderComponent(
      React.createElement(ParsingExtractPanel, {
        documentId: 'doc-1',
        activeElements: [
          {
            id: 'image:1:0',
            kind: 'image',
            page: 1,
            text: 'Revenue growth chart',
            visual_kind: 'chart',
          },
          {
            id: 'seal:1:0',
            kind: 'seal',
            page: 1,
            text: '杭州测试科技有限公司',
          },
        ],
      })
    )
    rendered.push(view)

    const selects = Array.from(view.container.querySelectorAll('select'))
    expect(selects.length).toBeGreaterThanOrEqual(1)
    const sourceKindSelect = selects[0] as HTMLSelectElement
    act(() => {
      sourceKindSelect.value = 'image'
      sourceKindSelect.dispatchEvent(new Event('change', { bubbles: true }))
    })

    expect(view.container.textContent).toContain('来源 visual kind')
    expect(view.container.textContent).toContain('chart')

    act(() => {
      sourceKindSelect.value = 'seal'
      sourceKindSelect.dispatchEvent(new Event('change', { bubbles: true }))
    })

    expect(view.container.textContent).not.toContain('来源 visual kind')
  })

  it('does not render a visual kind selector when no image subtypes are available', () => {
    const view = renderComponent(
      React.createElement(ParsingExtractPanel, {
        documentId: 'doc-2',
        activeElements: [
          {
            id: 'seal:1:0',
            kind: 'seal',
            page: 1,
            text: '杭州测试科技有限公司',
          },
        ],
      })
    )
    rendered.push(view)

    expect(view.container.textContent).not.toContain('来源 visual kind')
  })
})
