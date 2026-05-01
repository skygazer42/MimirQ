// @vitest-environment jsdom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'

import { ParsingElementsPanel } from './parsing-elements-panel'

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

describe('parsing elements panel behavior', () => {
  it('filters image elements by visual kind', () => {
    const view = renderComponent(
      React.createElement(ParsingElementsPanel, {
        elements: [
          {
            id: 'image:1:0',
            kind: 'image',
            page: 1,
            text: 'Revenue growth chart',
            visual_kind: 'chart',
          },
          {
            id: 'image:1:1',
            kind: 'image',
            page: 1,
            text: '扫码二维码',
            visual_kind: 'qr',
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

    const expandButton = Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.trim() === '展开')
    expect(expandButton).toBeTruthy()
    act(() => {
      expandButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(view.container.textContent).toContain('Revenue growth chart')
    expect(view.container.textContent).toContain('扫码二维码')
    expect(view.container.textContent).toContain('杭州测试科技有限公司')

    const imageFilter = Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('图片'))
    expect(imageFilter).toBeTruthy()
    act(() => {
      imageFilter?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    const chartFilter = Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.trim() === 'chart')
    expect(chartFilter).toBeTruthy()
    act(() => {
      chartFilter?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(view.container.textContent).toContain('Revenue growth chart')
    expect(view.container.textContent).not.toContain('扫码二维码')
    expect(view.container.textContent).not.toContain('杭州测试科技有限公司')
  })

  it('hides the image subtype filter when no image subtype exists', () => {
    const view = renderComponent(
      React.createElement(ParsingElementsPanel, {
        elements: [
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

    const expandButton = Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.trim() === '展开')
    expect(expandButton).toBeTruthy()
    act(() => {
      expandButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(view.container.textContent).not.toContain('全部图片子类')
  })
})
