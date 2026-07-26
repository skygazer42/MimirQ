// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}))

import { KgNetworkAnalysisPanel } from './kg-network-analysis-panel'

describe('KgNetworkAnalysisPanel accessibility', () => {
  let container: HTMLDivElement
  let root: ReturnType<typeof createRoot>

  beforeEach(() => {
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean })
      .IS_REACT_ACT_ENVIRONMENT = true
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      writable: true,
      value: vi.fn().mockReturnValue({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    })
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    document.body.innerHTML = ''
  })

  it('moves and resets the panel from the keyboard', () => {
    act(() => {
      root.render(
        <KgNetworkAnalysisPanel
          nodes={[
            { id: 'node-a', label: 'Node A', type: 'doc' },
            { id: 'node-b', label: 'Node B', type: 'doc' },
          ] as never}
          links={[{ source: 'node-a', target: 'node-b', label: 'rel' }] as never}
          selectedNodeId="node-a"
        />
      )
    })

    const panel = container.querySelector(
      '#kg-network-analysis-panel'
    ) as HTMLElement | null
    const dragHandle = container.querySelector(
      '[aria-label="拖动图谱统计栏"]'
    ) as HTMLButtonElement | null

    act(() => {
      dragHandle?.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })
      )
    })
    expect(panel?.style.transform).toContain('24px')

    act(() => {
      dragHandle?.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Home', bubbles: true })
      )
    })
    expect(panel?.style.transform).toBe('translate3d(0px, 0px, 0)')
  })
})
