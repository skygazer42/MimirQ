// @vitest-environment jsdom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@tanstack/react-query', () => ({
  useQuery: () => ({
    data: { collections: [] },
    isFetching: false,
    error: null,
    refetch: vi.fn(),
  }),
}))

vi.mock('@/hooks/use-media-query', () => ({
  useMediaQuery: () => false,
}))

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}))

import { RagvizSimilarityWorkbench } from './similarity-workbench'

describe('RagvizSimilarityWorkbench accessibility', () => {
  let container: HTMLDivElement
  let root: ReturnType<typeof createRoot>

  beforeEach(() => {
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean })
      .IS_REACT_ACT_ENVIRONMENT = true
    localStorage.clear()
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    document.body.innerHTML = ''
    localStorage.clear()
  })

  it('marks collapsed sidebars as inert', () => {
    act(() => {
      root.render(<RagvizSimilarityWorkbench />)
    })

    const leftSidebar = container.querySelector(
      '[role="separator"][aria-label="调整左侧栏宽度"]'
    )?.parentElement as HTMLElement | null
    const rightSidebar = container.querySelector(
      '[role="separator"][aria-label="调整右侧栏宽度"]'
    )?.parentElement as HTMLElement | null

    const leftToggle = container.querySelector(
      '[aria-label="收起左侧栏"]'
    ) as HTMLButtonElement | null
    const rightToggle = container.querySelector(
      '[aria-label="收起右侧栏"]'
    ) as HTMLButtonElement | null
    expect(leftToggle).not.toBeNull()
    expect(rightToggle).not.toBeNull()

    act(() => {
      leftToggle?.click()
    })

    expect(leftSidebar?.getAttribute('aria-hidden')).toBe('true')
    expect(leftSidebar?.hasAttribute('inert')).toBe(true)

    act(() => {
      rightToggle?.click()
    })

    expect(rightSidebar?.getAttribute('aria-hidden')).toBe('true')
    expect(rightSidebar?.hasAttribute('inert')).toBe(true)
  })

  it('resizes the left sidebar from the keyboard', () => {
    act(() => {
      root.render(<RagvizSimilarityWorkbench />)
    })

    const separator = container.querySelector(
      '[role="separator"][aria-label="调整左侧栏宽度"]'
    ) as HTMLElement | null
    expect(separator?.getAttribute('aria-valuenow')).toBe('312')

    act(() => {
      separator?.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })
      )
    })

    expect(separator?.getAttribute('aria-valuenow')).toBe('336')
  })
})
