// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('next-intl', () => ({ useTranslations: () => (key: string) => key }))
import { ParsingLeftPanel } from './parsing-left-panel'

const cleanups: Array<() => void> = []

function mount(element: React.ReactElement) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  let mounted = true
  const unmount = () => {
    if (mounted) {
      mounted = false
      act(() => root.unmount())
      container.remove()
    }
  }
  cleanups.push(unmount)
  act(() => root.render(element))
  return { container, unmount }
}

function startResize(element: Element) {
  act(() =>
    element.dispatchEvent(
      new PointerEvent('pointerdown', { bubbles: true, pointerId: 1, pointerType: 'mouse', button: 0, clientX: 100 }),
    ),
  )
  expect(document.body.style.cursor).toBe('col-resize')
  expect(document.body.style.userSelect).toBe('none')
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  localStorage.clear()
  document.body.style.cursor = 'text'
  document.body.style.userSelect = 'auto'
})

afterEach(() => {
  for (const cleanup of cleanups.splice(0)) cleanup()
  act(() => window.dispatchEvent(new PointerEvent('pointercancel', { pointerId: 1 })))
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  vi.restoreAllMocks()
})

describe('parsing left-panel resize ownership', () => {
  it('keeps only the latest drag owner and its pointerup write', () => {
    const view = mount(
      <ParsingLeftPanel collapsed={false} onToggleCollapsed={() => {}}>
        content
      </ParsingLeftPanel>,
    )
    const writes = vi.spyOn(window.localStorage, 'setItem')
    const slider = view.container.querySelector('[aria-label="调整文档列表宽度"]')!
    startResize(slider)
    startResize(slider)
    act(() => window.dispatchEvent(new PointerEvent('pointerup', { pointerId: 1 })))
    expect(document.body.style.cursor).toBe('text')
    expect(document.body.style.userSelect).toBe('auto')
    expect(writes.mock.calls.filter(([key]) => key === 'mimirq.parsing.leftPanelWidth')).toHaveLength(1)
  })

  it('releases the left panel global drag effects when its view unmounts', () => {
    const view = mount(
      <ParsingLeftPanel collapsed={false} onToggleCollapsed={() => {}}>
        content
      </ParsingLeftPanel>,
    )
    startResize(view.container.querySelector('[aria-label="调整文档列表宽度"]')!)

    view.unmount()

    expect(document.body.style.cursor).toBe('text')
    expect(document.body.style.userSelect).toBe('auto')
  })

  it('keeps ordinary pointerup cleanup for the left panel', () => {
    const view = mount(
      <ParsingLeftPanel collapsed={false} onToggleCollapsed={() => {}}>
        content
      </ParsingLeftPanel>,
    )
    startResize(view.container.querySelector('[aria-label="调整文档列表宽度"]')!)
    act(() => window.dispatchEvent(new PointerEvent('pointerup', { pointerId: 1 })))

    expect(document.body.style.cursor).toBe('text')
    expect(document.body.style.userSelect).toBe('auto')
  })
})
