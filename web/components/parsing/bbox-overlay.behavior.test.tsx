// @vitest-environment happy-dom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { BboxOverlay, type BboxOverlayItem } from './bbox-overlay'

const roots = new Set<Root>()

function box(left: number): BboxOverlayItem {
  return {
    id: 'shared-block',
    position: { pages: [0], left, right: left + 10, top: 10, bottom: 20, raw: `position:${left}` },
  }
}

function mount(items: BboxOverlayItem[], click?: (id: string) => void) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  roots.add(root)
  function render(next: BboxOverlayItem[]) {
    act(() =>
      root.render(
        <BboxOverlay
          items={next}
          scale={1}
          pageBaseWidth={100}
          pageBaseHeight={100}
          showAll
          activeIds={new Set()}
          hoveredIds={new Set()}
          onClickId={click}
        />,
      ),
    )
  }
  render(items)
  return { container, render }
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
})

afterEach(() => {
  for (const root of roots) act(() => root.unmount())
  roots.clear()
  document.body.replaceChildren()
})

describe('physical box identity and actual actions', () => {
  it('preserves focus on the same physical position when one logical block positions are reordered', () => {
    const first = box(10)
    const second = box(50)
    const view = mount([first, second], vi.fn())
    const focused = view.container.querySelectorAll('button')[1]
    focused.focus()

    view.render([second, first])

    expect(document.activeElement).toBe(focused)
    expect(focused.style.left).toBe('50px')
  })

  it('does not create an action button when the caller only requests a visual annotation', () => {
    const view = mount([box(10)])

    expect(view.container.querySelectorAll('[data-bbox-overlay-id]')).toHaveLength(1)
    expect(view.container.querySelectorAll('button')).toHaveLength(0)
  })

  it('keeps one physical box for repeated identical positions while retaining distinct positions', () => {
    const first = box(10)
    const view = mount([first, { ...first, position: { ...first.position } }, box(50)], vi.fn())

    expect(view.container.querySelectorAll('button')).toHaveLength(2)
  })

  it('does not invent a spatial hint for an activation without a pointer location', () => {
    const click = vi.fn()
    const view = mount([box(10)], click)

    act(() => view.container.querySelector('button')!.click())

    expect(click).toHaveBeenCalledExactlyOnceWith('shared-block')
  })
})
